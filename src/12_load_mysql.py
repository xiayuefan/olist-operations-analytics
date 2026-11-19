"""在一个事务中从已核对的 Parquet 装载 MySQL。"""

import argparse
from collections import defaultdict
from getpass import getpass
import hashlib
from itertools import islice
import json

import numpy as np
import pandas as pd
import pymysql

from mysql_input import MANIFEST_PATH, PROJECT_DIR, check_input_relationships, read_manifest


SCHEMA = "olist_operations_analytics"
LOCK_NAME = SCHEMA + ".parquet_v1"
BATCH_SIZE = 1000


def quote(name):
    return "\x60" + name.replace("\x60", "\x60\x60") + "\x60"


def read_verified_parquet(manifest):
    parquet_dir = PROJECT_DIR / "data" / "processed" / "mysql_input_v1"
    report_path = PROJECT_DIR / "reports" / "mysql_input_v1" / "parquet_run_info_v1.json"
    info = json.loads(report_path.read_text(encoding="utf-8"))
    if hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest() != info["manifest_sha256"]:
        raise ValueError("入库清单已变化，请重新导出并核对 Parquet")
    if set(info["tables"]) != set(manifest["tables"]):
        raise ValueError("Parquet 报告中的表清单不完整")

    tables = {}
    for name, spec in manifest["tables"].items():
        path = parquet_dir / (name + ".parquet")
        if hashlib.sha256(path.read_bytes()).hexdigest() != info["tables"][name]["parquet_sha256"]:
            raise ValueError("Parquet 校验值与导出报告不符 " + name)
        frame = pd.read_parquet(path, engine="pyarrow")
        if list(frame.columns) != list(spec["columns"]) or len(frame) != spec["expected_rows"]:
            raise ValueError("Parquet 字段或行数与清单不符 " + name)
        if frame.duplicated(spec["primary_key"]).any():
            raise ValueError("Parquet 主键重复 " + name)
        required = [column for column in spec["columns"] if column not in spec["nullable"]]
        if frame[required].isna().any().any():
            raise ValueError("Parquet 必填字段存在缺失 " + name)
        tables[name] = frame
    check_input_relationships(tables, manifest["relationships"])
    return tables


def connect_local(user, password, port):
    return pymysql.connect(
        host="127.0.0.1", port=port, user=user, password=password, database=SCHEMA,
        charset="utf8mb4", ssl={"check_hostname": False}, autocommit=False,
        sql_mode="STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION", connect_timeout=5,
    )


def check_mysql_schema(cursor, manifest):
    specs = manifest["tables"]
    cursor.execute(
        "SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE'", (SCHEMA,)
    )
    if dict(cursor.fetchall()) != {name: "InnoDB" for name in specs}:
        raise ValueError("目标库的表清单或存储引擎不符，请核对建表结果")

    cursor.execute(
        "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE "
        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s", (SCHEMA,)
    )
    actual = {(name, column): (kind.upper(), nullable) for name, column, kind, nullable in cursor}
    expected = {
        (name, column): (kind, "YES" if column in spec["nullable"] else "NO")
        for name, spec in specs.items() for column, kind in spec["columns"].items()
    }
    if actual != expected:
        raise ValueError("目标库的字段类型或可空性与入库清单不符")

    cursor.execute(
        "SELECT TABLE_NAME, CONSTRAINT_NAME, COLUMN_NAME, REFERENCED_TABLE_SCHEMA, "
        "REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
        "WHERE TABLE_SCHEMA=%s AND (CONSTRAINT_NAME='PRIMARY' OR REFERENCED_TABLE_NAME IS NOT NULL) "
        "ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION", (SCHEMA,)
    )
    primary = defaultdict(list)
    foreign = set()
    for table, constraint, column, parent_schema, parent, parent_column in cursor:
        if constraint == "PRIMARY":
            primary[table].append(column)
        else:
            foreign.add((table, column, parent_schema, parent, parent_column))
    expected_foreign = {
        (link["child"], child_col, SCHEMA, link["parent"], parent_col)
        for link in manifest["relationships"] if link["required"]
        for child_col, parent_col in zip(link["columns"], link["parent_columns"])
    }
    if dict(primary) != {name: spec["primary_key"] for name, spec in specs.items()} or foreign != expected_foreign:
        raise ValueError("目标库的主键或外键与入库清单不符")


def table_counts(cursor, specs):
    counts = {}
    for name in specs:
        cursor.execute("SELECT COUNT(*) FROM " + quote(name))
        counts[name] = cursor.fetchone()[0]
    return counts


def mysql_value(value):
    # Pandas 缺失值用 None 传递给驱动，由驱动写成 SQL NULL。
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, np.generic):
        return value.item()
    return value


def insert_table(cursor, name, frame):
    fields = ", ".join(quote(column) for column in frame.columns)
    placeholders = ", ".join(["%s"] * len(frame.columns))
    statement = "INSERT INTO {} ({}) VALUES ({})".format(quote(name), fields, placeholders)
    rows = (tuple(mysql_value(value) for value in row) for row in frame.itertuples(index=False, name=None))
    while True:
        batch = list(islice(rows, BATCH_SIZE))
        if not batch:
            break
        cursor.executemany(statement, batch)


def check_loaded_data(cursor, manifest, tables):
    specs = manifest["tables"]
    counts = table_counts(cursor, specs)
    if counts != {name: spec["expected_rows"] for name, spec in specs.items()}:
        raise ValueError("装载后的表行数与清单不符")
    for name, spec in specs.items():
        for column, expected in spec.get("expected_totals", {}).items():
            cursor.execute("SELECT SUM({}) FROM {}".format(quote(column), quote(name)))
            if cursor.fetchone()[0] != expected:
                raise ValueError("装载后的整数分金额不符 " + name + "." + column)

    cursor.execute(
        "SELECT COUNT(*) FROM products "
        "WHERE NOT (flag_weight_zero <=> CASE WHEN product_weight_g IS NULL "
        "THEN NULL ELSE product_weight_g = 0 END)"
    )
    if cursor.fetchone()[0]:
        raise ValueError("装载后的零重量标记与重量字段不一致")
    cursor.execute("SELECT COUNT(*) FROM products WHERE flag_weight_zero IS NULL")
    if cursor.fetchone()[0] != int(tables["products"]["flag_weight_zero"].isna().sum()):
        raise ValueError("装载后的重量标记空值数不符")
    return counts


def load_transaction(connection, manifest, tables):
    with connection.cursor() as cursor:
        cursor.execute("SELECT GET_LOCK(%s, 5)", (LOCK_NAME,))
        if cursor.fetchone()[0] != 1:
            raise ValueError("另一个装载任务正在运行")
        try:
            cursor.execute("SET SESSION foreign_key_checks = 1")
            connection.begin()
            check_mysql_schema(cursor, manifest)
            occupied = [name for name, count in table_counts(cursor, manifest["tables"]).items() if count]
            if occupied:
                raise ValueError("目标表已有数据，请先运行装载核对 SQL：" + ", ".join(occupied))

            # 清单顺序保证先写入被引用的父表，再写入子表。
            for name in manifest["tables"]:
                insert_table(cursor, name, tables[name])
                print("{} 已写入 {:,} 行，等待提交".format(name, len(tables[name])), flush=True)
            counts = check_loaded_data(cursor, manifest, tables)
            connection.commit()
            return counts
        except BaseException:
            if connection.open:
                connection.rollback()
            raise
        finally:
            if connection.open:
                cursor.execute("SELECT RELEASE_LOCK(%s)", (LOCK_NAME,))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default="root", help="本机 MySQL 账号")
    parser.add_argument("--port", type=int, default=3306)
    args = parser.parse_args()
    try:
        manifest = read_manifest()
        tables = read_verified_parquet(manifest)
        password = getpass("MySQL 密码: ")
        connection = connect_local(args.user, password, args.port)
        try:
            counts = load_transaction(connection, manifest, tables)
        finally:
            connection.close()
    except (OSError, ValueError, pymysql.MySQLError) as exc:
        parser.exit(1, "装载失败 " + str(exc) + "\n")
    print("提交成功。已核对 {} 张表、{:,} 行和三项整数分金额。".format(len(counts), sum(counts.values())))


if __name__ == "__main__":
    main()
