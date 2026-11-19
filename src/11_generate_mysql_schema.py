"""从入库清单生成第 24 课的 MySQL 建表 SQL。"""

from mysql_input import PROJECT_DIR, read_manifest


SCHEMA = "olist_operations_analytics"
COLLATION = "utf8mb4_0900_bin"
SQL_TYPES = {
    "CHAR(32)", "CHAR(5)", "CHAR(2)", "VARCHAR(128)", "TEXT",
    "BIGINT", "INT", "TINYINT", "DOUBLE", "DATETIME",
}


def quote(name):
    return "\x60" + name.replace("\x60", "\x60\x60") + "\x60"


def column_list(names):
    return ", ".join(quote(name) for name in names)


def build_ddl(manifest):
    tables = manifest["tables"]
    links = [link for link in manifest["relationships"] if link["required"]]
    statements = [
        "-- 从 config/mysql_input_v1.json 生成。按父表在前、子表在后的顺序建表。",
        "CREATE DATABASE IF NOT EXISTS {} DEFAULT CHARACTER SET utf8mb4 COLLATE {};".format(
            quote(SCHEMA), COLLATION),
        "USE {};".format(quote(SCHEMA)),
    ]
    created = set()
    for name, spec in tables.items():
        columns = spec["columns"]
        nullable = set(spec["nullable"])
        key = spec["primary_key"]
        if not key or not set(key).issubset(columns) or nullable.intersection(key):
            raise ValueError("主键字段须存在且不可空：" + name)
        if not set(columns.values()).issubset(SQL_TYPES) or not nullable.issubset(columns):
            raise ValueError("字段类型或可空字段与清单不符：" + name)

        fields = [
            "{} {} {}".format(quote(column), sql_type, "NULL" if column in nullable else "NOT NULL")
            for column, sql_type in columns.items()
        ]
        fields.append("PRIMARY KEY ({})".format(column_list(key)))

        for link in links:
            if link["child"] != name:
                continue
            parent = link["parent"]
            child_cols = link["columns"]
            parent_cols = link["parent_columns"]
            if parent not in created or parent_cols != tables[parent]["primary_key"]:
                raise ValueError("请先定义被引用的父表主键：" + parent)
            if [columns[c] for c in child_cols] != [tables[parent]["columns"][c] for c in parent_cols]:
                raise ValueError("外键字段类型与父表不一致：" + name)
            constraint = "fk_" + name + "_" + parent
            fields.append(
                "CONSTRAINT {} FOREIGN KEY ({}) REFERENCES {} ({}) "
                "ON UPDATE RESTRICT ON DELETE RESTRICT".format(
                    quote(constraint), column_list(child_cols), quote(parent), column_list(parent_cols)
                )
            )

        statements.append(
            "\n-- {}\nCREATE TABLE IF NOT EXISTS {} (\n    {}\n)"
            " ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE {};".format(
                spec["grain"], quote(name), ",\n    ".join(fields), COLLATION
            )
        )
        created.add(name)
    return "\n".join(statements) + "\n"


def main():
    path = PROJECT_DIR / "sql" / "01_create_schema.sql"
    path.parent.mkdir(exist_ok=True)
    path.write_text(build_ddl(read_manifest()), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
