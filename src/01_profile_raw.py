"""第 1 阶段：只读原始 CSV，生成盘点报告；不清洗、不写数据库。

兼容 Python 3.7+、Pandas 1.1+。
从项目任意位置运行，输入目录默认是项目同级 archive。
"""

import argparse
import json
import platform
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
SPECS = {
    "orders": ("olist_orders_dataset.csv", ["order_id"], "一个订单"),
    "items": ("olist_order_items_dataset.csv", ["order_id", "order_item_id"], "一条订单商品明细"),
    "payments": ("olist_order_payments_dataset.csv", ["order_id", "payment_sequential"], "一条支付记录"),
    "reviews": ("olist_order_reviews_dataset.csv", [], "一条评价记录，需另核对候选键"),
    "customers": ("olist_customers_dataset.csv", ["customer_id"], "一个 customer_id 对应的客户资料"),
    "products": ("olist_products_dataset.csv", ["product_id"], "一个商品"),
    "sellers": ("olist_sellers_dataset.csv", ["seller_id"], "一个卖家"),
    "geolocation": ("olist_geolocation_dataset.csv", [], "一条邮编前缀地理记录，前缀非唯一"),
    "category_translation": ("product_category_name_translation.csv", ["product_category_name"], "一个品类翻译映射"),
}


def markdown_table(headers, rows):
    """只处理本脚本生成的汇总标签和值，不输出原始评价文本。"""
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    result = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    result.extend("| " + " | ".join(cell(v) for v in row) + " |" for row in rows)
    return "\n".join(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_DIR.parent / "archive")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "reports")
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    missing_files = [name for name, _, _ in SPECS.values() if not (data_dir / name).is_file()]
    if missing_files:
        raise FileNotFoundError("缺少原始文件：" + ", ".join(missing_files))

    tables, table_rows, column_rows = {}, [], []
    for alias, (filename, key, grain) in SPECS.items():
        # ID/邮编先保留字符串；仅空字符串视为缺失，保留原始文字 NA 等。
        df = pd.read_csv(data_dir / filename, encoding="utf-8-sig", dtype=str,
                         keep_default_na=False, na_values=[""])
        tables[alias] = df
        table_rows.append({
            "table": alias, "file": filename, "rows": len(df), "columns": len(df.columns),
            "grain": grain, "duplicate_rows_after_first": int(df.duplicated().sum()),
            "candidate_key": "+".join(key) if key else "未指定",
            "duplicate_keys_after_first": int(df.duplicated(key).sum()) if key else None,
            "null_key_rows": int(df[key].isna().any(axis=1).sum()) if key else None,
        })
        for col in df.columns:
            column_rows.append({
                "table": alias, "column": col, "rows": len(df),
                "missing_rows": int(df[col].isna().sum()),
                "missing_rate": float(df[col].isna().mean()),
                "distinct_non_null_values": int(df[col].nunique()),
            })

    # 未匹配行单独报告，不能据此自动删除；品类翻译缺失与主外键错误含义不同。
    relations = [
        ("orders", "customer_id", "customers", "customer_id"),
        ("items", "order_id", "orders", "order_id"),
        ("items", "product_id", "products", "product_id"),
        ("items", "seller_id", "sellers", "seller_id"),
        ("payments", "order_id", "orders", "order_id"),
        ("reviews", "order_id", "orders", "order_id"),
        ("products", "product_category_name", "category_translation", "product_category_name"),
    ]
    relation_rows = []
    for child, child_key, parent, parent_key in relations:
        values = tables[child][child_key]
        parent_values = tables[parent][parent_key].dropna()
        relation_rows.append({
            "relationship": "{}.{} -> {}.{}".format(child, child_key, parent, parent_key),
            "child_null_rows": int(values.isna().sum()),
            "unmatched_non_null_rows": int((values.notna() & ~values.isin(parent_values)).sum()),
            "parent_key_unique": bool(parent_values.is_unique),
        })

    orders, customers = tables["orders"], tables["customers"]
    purchased = pd.to_datetime(orders["order_purchase_timestamp"], errors="coerce")
    status = orders["order_status"].value_counts(dropna=False)
    monthly = purchased.dt.strftime("%Y-%m").value_counts().sort_index()
    approved = pd.to_datetime(orders["order_approved_at"], errors="coerce")
    carrier = pd.to_datetime(orders["order_delivered_carrier_date"], errors="coerce")
    delivered = pd.to_datetime(orders["order_delivered_customer_date"], errors="coerce")
    estimated = pd.to_datetime(orders["order_estimated_delivery_date"], errors="coerce")
    completed = orders["order_status"].eq("delivered")
    diagnostics = {
        "订单ID不同值": int(orders["order_id"].nunique()),
        "customer_id不同值": int(customers["customer_id"].nunique()),
        "customer_unique_id不同值": int(customers["customer_unique_id"].nunique()),
        "已交付订单缺失实际送达时间": int((completed & delivered.isna()).sum()),
        "已交付订单缺失预计送达时间": int((completed & estimated.isna()).sum()),
        "审批早于下单的订单": int((approved < purchased).sum()),
        "交承运商早于下单的订单": int((carrier < purchased).sum()),
        "送达早于交承运商的订单": int((delivered < carrier).sum()),
        "评价ID重复行数_首条之后": int(tables["reviews"].duplicated(["review_id"]).sum()),
        "评价表涉及多条评价的订单数": int((tables["reviews"]["order_id"].value_counts() > 1).sum()),
        "地理表邮编前缀不同值": int(tables["geolocation"]["geolocation_zip_code_prefix"].nunique()),
    }
    for alias in ("items", "payments", "reviews"):
        has_record = orders["order_id"].isin(tables[alias]["order_id"])
        diagnostics["缺少{}记录的订单数".format(alias)] = int((~has_record).sum())
        diagnostics["已交付但缺少{}记录的订单数".format(alias)] = int((completed & ~has_record).sum())
    for col, parsed in [
        ("order_purchase_timestamp", purchased), ("order_approved_at", approved),
        ("order_delivered_carrier_date", carrier),
        ("order_delivered_customer_date", delivered), ("order_estimated_delivery_date", estimated),
    ]:
        diagnostics["非空但日期解析失败_" + col] = int((orders[col].notna() & parsed.isna()).sum())

    # 中文说明只是辅助数据，先检测编码并核对字段覆盖，不视为项目指令。
    dictionary_info = {"exists": False}
    dictionary_path = data_dir / "数据含义.csv"
    if dictionary_path.exists():
        try:
            dictionary = pd.read_csv(dictionary_path, encoding="utf-8-sig", dtype=str)
            dictionary_encoding = "utf-8-sig"
        except UnicodeDecodeError:
            dictionary = pd.read_csv(dictionary_path, encoding="gb18030", dtype=str)
            dictionary_encoding = "gb18030（兼容 GBK）"
        expected_fields = {(filename, col) for alias, (filename, _, _) in SPECS.items()
                           for col in tables[alias].columns}
        required_cols = {"数据表文件名", "字段名"}
        if not required_cols.issubset(dictionary.columns):
            raise ValueError("中文字段说明的列名与预期不同，请手动核对")
        documented_fields = set(zip(dictionary["数据表文件名"], dictionary["字段名"]))
        dictionary_info = {
            "exists": True, "encoding": dictionary_encoding, "rows": len(dictionary),
            "actual_field_count": len(expected_fields),
            "undocumented_fields": sorted(expected_fields - documented_fields),
            "extra_documented_fields": sorted(documented_fields - expected_fields),
        }

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(table_rows).to_csv(output_dir / "01_table_inventory.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(column_rows).to_csv(output_dir / "01_column_profile.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(relation_rows).to_csv(output_dir / "01_relationship_checks.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame({"month": monthly.index, "orders": monthly.values}).to_csv(
        output_dir / "01_monthly_coverage.csv", index=False, encoding="utf-8-sig")
    summary = {
        "source_dir": str(data_dir), "python": platform.python_version(), "pandas": pd.__version__,
        "purchase_time_min": str(purchased.min()), "purchase_time_max": str(purchased.max()),
        "tables": table_rows, "status_counts": {str(k): int(v) for k, v in status.items()},
        "diagnostics": diagnostics, "dictionary": dictionary_info,
    }
    (output_dir / "01_profile_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    nonzero_missing = sorted([r for r in column_rows if r["missing_rows"] > 0],
                             key=lambda r: r["missing_rate"], reverse=True)
    report = [
        "# 原始数据盘点", "",
        "来源：`{}`。由 `src/01_profile_raw.py` 生成；读取全部 9 张原始表，没有清洗或修改原文件。".format(data_dir), "",
        "本报告描述原始数据，不代表清洗已经完成，也不把异常数量直接解释为业务损失。", "",
        "## 表规模与粒度", "",
        markdown_table(["表", "行数", "列数", "整行重复（首条之后）", "粒度"],
                       [[r["table"], "{:,}".format(r["rows"]), r["columns"],
                         "{:,}".format(r["duplicate_rows_after_first"]), r["grain"]] for r in table_rows]), "",
        "## 下单时间与状态", "",
        "全部订单的下单时间为 {} 至 {}。这只是最小/最大值，不能据此认为边界月份完整或观察窗口已经成熟。".format(purchased.min(), purchased.max()), "",
        markdown_table(["订单状态", "订单数"], [[k, "{:,}".format(v)] for k, v in status.items()]), "",
        "逐月订单量见 `01_monthly_coverage.csv`；主要经营区间和复购观察截止日留待下一阶段确定。", "",
        "## 候选键检查", "",
        markdown_table(["表", "候选键", "键重复（首条之后）", "键含空值的行数"],
                       [[r["table"], r["candidate_key"], r["duplicate_keys_after_first"], r["null_key_rows"]]
                        for r in table_rows if r["candidate_key"] != "未指定"]), "",
        "评价与地理表未预设主键；下面单独展示重复情况。整行重复数不能替代业务键检查。", "",
        "## 关联检查", "",
        markdown_table(["关系", "左表键缺失行", "非空但未匹配行", "右表键唯一"],
                       [[r["relationship"], r["child_null_rows"], r["unmatched_non_null_rows"],
                         r["parent_key_unique"]] for r in relation_rows]), "",
        "## 身份、记录覆盖与时间检查", "",
        markdown_table(["观察项", "数量"], [[k, "{:,}".format(v)] for k, v in diagnostics.items()]), "",
        "时间比较仅对两端可解析的记录生效；缺失值另报，不能把未比较的记录视为正常。", "",
        "## 有缺失的字段", "",
        markdown_table(["表", "字段", "缺失行数", "缺失率"],
                       [[r["table"], r["column"], "{:,}".format(r["missing_rows"]),
                         "{:.2%}".format(r["missing_rate"])] for r in nonzero_missing]), "",
        "缺失定义：CSV 的空字段。缺失值是数据现象，是否清洗要结合状态和业务含义，评价文本空白尤其不能直接删除。", "",
        "## 中文字段说明", "",
        "```json", json.dumps(dictionary_info, ensure_ascii=False, indent=2), "```", "",
        "## 解释时注意", "",
        "- `customer_unique_id` 的不同值数包含原始客户表的全部记录，不是已交付购买客户数。",
        "- 地理表前缀不唯一，不应直接以邮编前缀连接原始表后对订单金额求和。",
        "- 一单可能包含多条商品、支付和评价，关联前要控制粒度，不能直接拼成大表。",
        "- 异常在下一阶段按规则处理；本脚本只观察，不自动丢弃或填补。", "",
        "运行环境：Python {}，Pandas {}。".format(platform.python_version(), pd.__version__), "",
    ]
    (output_dir / "01_原始数据盘点.md").write_text("\n".join(report), encoding="utf-8")
    print("已盘点 {} 张原始表；未修改原始 CSV。".format(len(tables)))
    print("订单数：{:,}；不同 customer_unique_id：{:,}".format(len(orders), customers["customer_unique_id"].nunique()))
    print("报告：{}".format(output_dir / "01_原始数据盘点.md"))


if __name__ == "__main__":
    main()
