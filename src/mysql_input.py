"""读取入库清单，恢复 CSV 类型并核对主键、关联与金额。"""

import json
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_DIR / "config" / "mysql_input_v1.json"
TEXT_PATTERNS = {
    "CHAR(32)": "[0-9a-f]{32}",
    "CHAR(5)": "[0-9]{5}",
    "CHAR(2)": "[A-Z]{2}",
}


def read_manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def restore_column_type(column, mysql_type):
    """将一个 CSV 字段转为入库准备阶段的 Pandas 类型。"""
    present = column.dropna()
    if mysql_type in TEXT_PATTERNS:
        if not present.str.fullmatch(TEXT_PATTERNS[mysql_type]).all():
            raise ValueError("标识或编码格式不符合清单")
        return column.astype("string")
    if mysql_type == "VARCHAR(128)":
        if present.str.len().gt(128).any():
            raise ValueError("文本超过 128 字符")
        return column.astype("string")
    if mysql_type == "TEXT":
        if present.str.encode("utf-8").str.len().gt(65535).any():
            raise ValueError("文本超过 TEXT 字节容量")
        return column.astype("string")
    if mysql_type == "DATETIME":
        return pd.to_datetime(column, format="%Y-%m-%d %H:%M:%S", errors="raise")
    if mysql_type == "TINYINT":
        # CSV 中的 False 是非空字符串，布尔值按字面值映射。
        if not present.isin(["True", "False"]).all():
            raise ValueError("质量标记的值应为 True 或 False")
        return column.map({"True": True, "False": False}).astype("boolean")
    if mysql_type == "BIGINT":
        # 金额的源字段已经是整数分，避免先转浮点数再取整。
        if not present.str.fullmatch("[+-]?[0-9]+").all():
            raise ValueError("整数分金额包含非整数文本")
        values = pd.to_numeric(present, errors="raise")
        if any(not -(2 ** 63) <= int(value) < 2 ** 63 for value in values):
            raise ValueError("金额超出有符号 BIGINT 范围")
        return values.astype("Int64").reindex(column.index)
    if mysql_type == "INT":
        values = pd.to_numeric(column, errors="raise")
        if not values.dropna().between(-(2 ** 31), 2 ** 31 - 1).all():
            raise ValueError("数值超出有符号 INT 范围")
        return values.astype("Int64")
    if mysql_type == "DOUBLE":
        values = pd.to_numeric(column, errors="raise").astype("float64")
        if not np.isfinite(values.dropna()).all():
            raise ValueError("存在非有限数值")
        return values
    raise ValueError("清单包含未支持的类型 " + mysql_type)


def load_input_table(processed_dir, table_name, spec):
    raw = pd.read_csv(
        processed_dir / spec["source"], dtype=str, encoding="utf-8-sig",
        keep_default_na=False, na_values=[""],
    )
    fields = spec["columns"]
    missing = set(fields) - set(raw.columns)
    if missing:
        raise ValueError(table_name + " 缺少字段 " + ", ".join(sorted(missing)))
    data = pd.DataFrame(index=raw.index)
    for name, mysql_type in fields.items():
        try:
            data[name] = restore_column_type(raw[name], mysql_type)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(table_name + "." + name + " 类型转换失败") from exc
        if not data[name].isna().equals(raw[name].isna()):
            raise ValueError(table_name + "." + name + " 转换后缺失状态改变")

    required = [name for name in fields if name not in spec["nullable"]]
    if data[required].isna().any().any():
        raise ValueError(table_name + " 的必填字段有缺失")
    if len(data) != spec["expected_rows"] or data.duplicated(spec["primary_key"]).any():
        raise ValueError(table_name + " 的行数或主键与清单不符")
    for name, total in spec.get("expected_totals", {}).items():
        if data[name].sum() != total:
            raise ValueError(table_name + "." + name + " 的金额合计不符")
    return data


def check_input_relationships(tables, relationships):
    checks = []
    for link in relationships:
        child = tables[link["child"]][link["columns"]]
        parent = tables[link["parent"]][link["parent_columns"]]
        has_key = child.notna().all(axis=1)
        hit = pd.Series(
            pd.MultiIndex.from_frame(child).isin(pd.MultiIndex.from_frame(parent)),
            index=child.index,
        ) & has_key
        missing = int((~has_key).sum())
        unmatched = int((has_key & ~hit).sum())
        if link["required"] and (missing or unmatched):
            raise ValueError(link["child"] + " 到 " + link["parent"] + " 的必备关联存在缺口")
        checks.append({
            "来源表": link["child"],
            "键": " + ".join(link["columns"]),
            "目标表": link["parent"],
            "规则": "拟设外键" if link["required"] else "覆盖检查",
            "键缺失": missing,
            "键非空但未匹配": unmatched,
            "已匹配": int(hit.sum()),
        })
    return pd.DataFrame(checks)
