"""商品阶段独立导出：在项目目录运行 python src/07_clean_products.py。"""

import argparse
import hashlib
import json
import platform
from pathlib import Path

import pandas as pd

from items_cleaning import clean_order_items
from products_cleaning import (
    NUMERIC_COLS, check_product_numeric, clean_product_attributes,
    join_items_products, join_product_categories, product_attribute_coverage,
    reconcile_product_totals, summarize_product_metrics,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]


def read_source(path):
    # 保留 ID、原始金额字符串；空字段为缺失，便于与非空解析失败区分。
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig",
                       keep_default_na=False, na_values=[""])


def markdown_table(frame, include_index=False):
    if include_index:
        frame = frame.rename_axis(frame.index.name or "检查项").reset_index()

    def cell(value):
        return "缺失" if pd.isna(value) else str(value).replace("|", r"\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(map(str, frame.columns)) + " |",
        "| " + " | ".join(["---"] * len(frame.columns)) + " |",
    ]
    lines.extend("| " + " | ".join(cell(v) for v in row) + " |"
                 for row in frame.itertuples(index=False, name=None))
    return "\n".join(lines)


def write_report(report_dir, metrics, numeric_check, coverage, controls, untranslated):
    baseline = pd.DataFrame([
        ("商品记录 / 不同商品 ID", metrics["product_rows"]),
        ("翻译映射记录", metrics["translation_rows"]),
        ("原始非空品类种类", metrics["original_category_count"]),
        ("匹配英文品类商品", metrics["category_matched_products"]),
        ("原始品类缺失商品", metrics["category_missing_products"]),
        ("有原始品类但无翻译商品", metrics["category_untranslated_products"]),
        ("英文品类缺失商品合计", metrics["english_category_missing_products"]),
        ("重量为零商品", metrics["weight_zero_products"]),
        ("重量缺失商品", metrics["weight_missing_products"]),
        ("可计算体积商品", metrics["volume_eligible_products"]),
        ("无法计算体积商品", metrics["volume_unknown_products"]),
        ("关联后销售明细", metrics["item_rows"]),
        ("明细涉及订单", metrics["item_orders"]),
        ("明细组合主键重复数", metrics["item_primary_key_duplicates"]),
        ("明细未匹配商品数", metrics["items_without_product"]),
    ], columns=["检查项目", "数量"])
    lines = [
        "# 商品与品类翻译阶段报告 v1", "",
        "运行：python src/07_clean_products.py。独立读取商品、品类翻译、订单商品明细三张原表。"
        "本阶段使用全部销售明细，没有按订单状态或时间筛选；金额不是已交付口径。", "",
        "## 粒度与覆盖", "",
        markdown_table(baseline), "",
        "商品工作表一行一个 product_id；销售明细一行由 (order_id, order_item_id) 唯一标识。"
        "同一商品可在同一订单多条明细、多个订单中出现，不按 product_id 删除销售明细。"
        "两次关联均验证右侧键唯一：品类映射键、商品 ID。", "",
        "## 品类缺失原因", "",
        "原始品类缺失与非空品类未翻译分别标记，保留商品与销售明细。"
        "未将缺失译名猜测为某个品类，也未改写来源映射。以下按未翻译的原始品类计商品数。", "",
        markdown_table(untranslated), "",
        "## 数值与体积", "",
        markdown_table(numeric_check, include_index=True), "",
        "七个数值属性的非空值在本批数据中均为整数，使用可空 Int64；"
        "缺失保留未知，不填零。非空解析失败、非有限值、小数或负数会停止导出并要求核查。"
        "这里的整数限制是当前来源精度约定，不代表所有场景的尺寸、重量都必须为整数。", "",
        "体积特征为记录的长×宽×高，三边非空且大于零才计算；重量资格单独判断。"
        "重量为零的商品仍可能有完整尺寸。该特征尚未验证为实际包装体积或计费体积。"
        "本批可计算体积的中位数为 {} cm³，最大值为 {} cm³；"
        "仅凭极端值不能判为错误并删除。".format(
            metrics["volume_median_cm3"], metrics["volume_max_cm3"]), "",
        "## 属性缺失影响：商品与销售明细两种粒度", "",
        markdown_table(coverage, include_index=True), "",
        "同一商品可能出现多条销售明细，所以两列不应相等。各质量条件可能重叠，"
        "不能将这些行的数量相加当成去重后的异常总数。商品 ID 全部匹配也不代表属性全部完整。", "",
        "## 关联控制总额", "",
        markdown_table(controls, include_index=True), "",
        "商品金额与运费按原始字符串换算的整数分核对；属性关联应保持数量和金额。"
        "控制表差额须为零，组合主键仍唯一。", "",
        "## 文件与后续", "",
        "data/processed/products_v1 保存商品工作表、带商品属性的销售明细及经验证的原始翻译映射。"
        "本报告目录另存主键检查、数值检查、缺失清单、零重量清单、体积样本、"
        "两种粒度的属性覆盖、控制总额、metrics_v1.json 和 run_info_v1.json。", "",
        "CSV 不保存 Pandas 类型。重新读取时须显式恢复 ID 字符串、可空整数、布尔和日期；"
        "例如 flag_weight_zero 的缺失不应变成 False。", "",
        "原始品类缺失、未翻译品类、零重量及极端尺寸的业务原因仍待核查。"
        "下一课处理卖家表，再检查地理表；随后统一清洗产物与分析口径，接入 Parquet、MySQL 和 Power BI。", "",
    ]
    (report_dir / "商品阶段报告_v1.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_DIR.parent / "archive")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "data" / "processed" / "products_v1")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_DIR / "reports" / "products_v1")
    args = parser.parse_args()
    sources = {name: args.data_dir / name for name in [
        "olist_products_dataset.csv", "product_category_name_translation.csv",
        "olist_order_items_dataset.csv",
    ]}
    raw_products = read_source(sources["olist_products_dataset.csv"])
    raw_translation = read_source(sources["product_category_name_translation.csv"])
    raw_items = read_source(sources["olist_order_items_dataset.csv"])

    # 先处理属性，再增强明细。清洗函数返回副本，原始三张表仍保留。
    mapped = join_product_categories(raw_products, raw_translation)
    numeric_check = check_product_numeric(mapped)
    products = clean_product_attributes(mapped)
    items = clean_order_items(raw_items)
    joined = join_items_products(items, products)
    controls = reconcile_product_totals(items, joined)
    coverage = product_attribute_coverage(products, joined)
    metrics = summarize_product_metrics(products, raw_translation, joined)

    key_check = pd.DataFrame({
        "行数": [len(raw_products), len(raw_translation)],
        "键不同值数": [raw_products["product_id"].nunique(),
                     raw_translation["product_category_name"].nunique()],
        "键缺失数": [raw_products["product_id"].isna().sum(),
                   raw_translation["product_category_name"].isna().sum()],
        "键重复数_首条之后": [raw_products["product_id"].duplicated().sum(),
                            raw_translation["product_category_name"].duplicated().sum()],
    }, index=["商品表_product_id", "翻译表_product_category_name"])
    untranslated_products = products.loc[products["flag_category_untranslated"]]
    untranslated = untranslated_products.groupby("product_category_name").size().rename(
        "商品数").reset_index()

    # 输入、关联和控制总额通过后，再写本阶段独立目录，不改前面课程的产物。
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    for filename, frame in [
        ("products_clean_v1.csv", products),
        ("items_with_products_v1.csv", joined),
        ("category_translation_v1.csv", raw_translation),
    ]:
        frame.to_csv(args.output_dir / filename, index=False, encoding="utf-8-sig")
    for filename, frame in [
        ("product_key_check_v1.csv", key_check),
        ("product_numeric_check_v1.csv", numeric_check),
        ("product_numeric_range_v1.csv", products[NUMERIC_COLS].agg(["min", "median", "max"]).T),
        ("product_join_check_v1.csv", controls),
        ("item_attribute_coverage_v1.csv", coverage),
        ("product_category_coverage_v1.csv",
         products["category_match"].value_counts().to_frame("商品数")),
    ]:
        frame.to_csv(args.report_dir / filename, index_label="检查项", encoding="utf-8-sig")
    for filename, frame in [
        ("products_missing_category_v1.csv", products.loc[products["flag_category_missing"]]),
        ("products_untranslated_category_v1.csv", untranslated_products),
        ("untranslated_categories_v1.csv", untranslated),
        ("products_zero_weight_v1.csv", products.loc[products["flag_weight_zero"].fillna(False)]),
        ("products_missing_dimensions_v1.csv", products.loc[products["flag_dimensions_missing"]]),
        ("products_missing_content_metadata_v1.csv", products.loc[products["flag_content_metadata_missing"]]),
        ("products_largest_volume_v1.csv", products.nlargest(5, "product_volume_cm3")),
        ("products_without_item_lines_v1.csv", products.loc[
            ~products["product_id"].isin(items["product_id"])]),
    ]:
        frame.to_csv(args.report_dir / filename, index=False, encoding="utf-8-sig")

    run_info = {
        "version": "products_v1", "python": platform.python_version(), "pandas": pd.__version__,
        "source_dir": str(args.data_dir.resolve()),
        "source_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sources.items()},
        "output_dir": str(args.output_dir.resolve()),
        "product_grain": ["product_id"], "item_grain": ["order_id", "order_item_id"],
        "translation_key": "product_category_name",
        "join_validation": "两次左关联均为 many_to_one；保留所有商品和销售明细",
        "scope": "原始全部商品和全部销售明细，无订单状态、时间筛选",
        "deleted_product_rows": 0, "deleted_item_rows": 0, "money_unit": "BRL 整数分",
        "numeric_policy": "七属性可空整数；非空解析失败、非有限、小数、负数停止核查",
        "volume_policy": "三边非空且>0的记录尺寸乘积，单位cm3；未知不填零；不依赖重量",
        "category_policy": "保留原始品类与英文缺失，区分来源缺失和未翻译；不自动补译",
        "csv_read_policy": "ID字符串，七属性和体积Int64，flag_weight_zero为可空boolean；日期按格式解析",
        "pending_checks": [
            "原始品类缺失、两种未翻译品类、零重量及极端尺寸的原因",
            "卖家表、地理表、正式分析窗口与有效订单口径",
            "Parquet、MySQL、业务专题与Power BI",
        ],
    }
    for filename, payload in [("metrics_v1.json", metrics), ("run_info_v1.json", run_info)]:
        (args.report_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    write_report(args.report_dir, metrics, numeric_check, coverage, controls, untranslated)
    print("商品：{}；翻译映射：{}；销售明细：{}".format(
        metrics["product_rows"], metrics["translation_rows"], metrics["item_rows"]))
    print("商品金额、运费、明细数量控制差额均为0；明细组合主键重复数：{}".format(
        metrics["item_primary_key_duplicates"]))
    print("报告目录：" + str(args.report_dir.resolve()))


if __name__ == "__main__":
    main()
