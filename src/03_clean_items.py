"""商品明细 v1：从原始 CSV 生成清洗表、核对表及经营指标基线。

从项目根目录运行：python .\src\03_clean_items.py
"""

import argparse
import json
import platform
from pathlib import Path

import pandas as pd

from items_cleaning import (
    aggregate_order_items, check_item_references, clean_order_items,
    join_orders_items, reconcile_item_totals, summarize_item_metrics,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]


def read_source(path, usecols=None):
    return pd.read_csv(path, usecols=usecols, dtype=str, encoding="utf-8-sig",
                       keep_default_na=False, na_values=[""])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_DIR.parent / "archive")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "data" / "processed" / "items_v1")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_DIR / "reports" / "items_v1")
    args = parser.parse_args()

    raw = read_source(args.data_dir / "olist_order_items_dataset.csv")
    orders = read_source(args.data_dir / "olist_orders_dataset.csv")
    product_keys = read_source(args.data_dir / "olist_products_dataset.csv", ["product_id"])["product_id"]
    seller_keys = read_source(args.data_dir / "olist_sellers_dataset.csv", ["seller_id"])["seller_id"]

    cleaned = clean_order_items(raw)
    references = check_item_references(cleaned, product_keys, seller_keys)
    if references.ne(0).any().any():
        raise ValueError("商品或卖家关联键检查未通过，请先核查再输出结果")
    summary = aggregate_order_items(cleaned)
    joined = join_orders_items(orders, summary)
    reconcile = reconcile_item_totals(cleaned, summary, joined)
    metrics = summarize_item_metrics(cleaned, summary, joined)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in [
        ("items_clean_v1.csv", cleaned), ("order_item_summary_v1.csv", summary),
        ("orders_with_items_v1.csv", joined),
    ]:
        frame.to_csv(args.output_dir / name, index=False, encoding="utf-8-sig")
    references.to_csv(args.report_dir / "reference_check_v1.csv", encoding="utf-8-sig", index_label="检查项")
    reconcile.to_csv(args.report_dir / "reconcile_v1.csv", encoding="utf-8-sig", index_label="检查项")
    missing_status = joined.loc[joined["flag_missing_items"], "order_status"].value_counts()
    missing_status.rename_axis("order_status").reset_index(name="orders").to_csv(
        args.report_dir / "missing_items_by_status_v1.csv", index=False, encoding="utf-8-sig")
    joined.loc[joined["flag_progressed_missing_items"]].to_csv(
        args.report_dir / "priority_missing_items_v1.csv", index=False, encoding="utf-8-sig")
    (args.report_dir / "metrics_v1.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    shipping = cleaned["shipping_limit_date"]
    run_info = {
        "version": "items_v1", "source_dir": str(args.data_dir.resolve()),
        "python": platform.python_version(), "pandas": pd.__version__,
        "input_item_rows": len(raw), "output_item_rows": len(cleaned), "deleted_item_rows": 0,
        "money_unit": "整数分；BRL 展示时除以 100",
        "scope": "全量历史订单基线；已交付 GMV 不含运费；支付额尚待支付表核对",
        "shipping_limit_min": str(shipping.min()), "shipping_limit_max": str(shipping.max()),
        "pending_checks": [
            "发货截止时间的业务合理性，包含 2020 年截止记录",
            "正式分析区间与期末成熟度", "异常记录敏感性分析", "与支付表进行订单级金额核对",
        ],
        "csv_types": "CSV 不保存日期和可空整数类型；精确金额仍以整数分记录",
    }
    (args.report_dir / "run_info_v1.json").write_text(
        json.dumps(run_info, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(args.report_dir, metrics, references, reconcile, missing_status, run_info)

    print("明细：{}；订单汇总：{}；关联后订单：{}".format(
        metrics["item_rows"], metrics["orders_with_items"], metrics["all_order_rows"]))
    print("无明细订单：{}；优先核查：{}；零运费订单：{}".format(
        metrics["orders_missing_items"], metrics["priority_missing_items"], metrics["zero_freight_orders"]))
    print("已交付 GMV：{}；商品客单价：{}".format(
        "{:,.2f} BRL".format(metrics["delivered_goods_cents"] / 100) if metrics["delivered_goods_cents"] is not None else "无有效样本",
        "{:.2f} BRL".format(metrics["delivered_goods_aov_brl"]) if metrics["delivered_goods_aov_brl"] is not None else "无有效样本"))
    print("报告目录：{}".format(args.report_dir.resolve()))


def write_report(report_dir, metrics, references, reconcile, missing_status, run_info):
    def brl(cents):
        return "{:,.2f} BRL".format(cents / 100) if cents is not None else "无有效样本"

    lines = [
        "# 商品明细清洗与订单金额阶段报告 v1", "",
        "来源：`{}`。运行 `python .\\src\\03_clean_items.py` 可重新生成。".format(run_info["source_dir"]), "",
        "## 处理范围", "",
        "保留全部 {:,} 条原始明细，生成 {:,} 行订单汇总，再左关联 {:,} 笔订单。没有删除明细或将缺少明细的订单金额填为零。".format(
            metrics["item_rows"], metrics["orders_with_items"], metrics["all_order_rows"]), "",
        "组合键非空且唯一；明细序号规范为正整数并复核唯一性；金额从原始字符串精确换算为整数分；发货截止时间转换为时间类型。", "",
        "遇到缺少必需列、异常主键、无法精确换算的金额、负金额、非空日期无法解析或关联问题时，流程停止核查，不自动猜测和修复。零运费保留为业务特征；零商品金额和缺失发货截止时间另设标记。", "",
        "## 关联键检查", "",
        "| 检查项 | 商品关联 | 卖家关联 |", "| --- | ---: | ---: |",
    ]
    for label, row in references.iterrows():
        lines.append("| {} | {} | {} |".format(label, row["商品关联"], row["卖家关联"]))
    lines.extend([
        "", "这里仅检查维表主键和关联覆盖，商品、卖家属性仍待对应表阶段清洗。", "",
        "## 数量与金额核对", "",
        "| 检查项 | 明细层 | 订单汇总层 | 关联后 | 汇总差额 | 关联差额 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for label, row in reconcile.iterrows():
        lines.append("| {} | {} | {} | {} | {} | {} |".format(label, *[int(row[col]) for col in reconcile.columns]))
    lines.extend([
        "", "行数因粒度变化而减少；明细数量通过 item_line_count 累加核对，金额始终以整数分核对。", "",
        "## 订单覆盖", "",
        "{:,} 笔订单没有匹配到商品明细，其中 {} 笔处于审批或后续状态，列入优先核查清单。".format(
            metrics["orders_missing_items"], metrics["priority_missing_items"]), "",
        "| 状态 | 无明细订单数 |", "| --- | ---: |",
    ])
    for status, count in missing_status.items():
        lines.append("| {} | {} |".format(status, count))
    lines.extend([
        "", "当前全部已交付订单都能匹配商品明细。未匹配订单保留其状态与缺失金额，具体原因不能仅凭状态确定。", "",
        "## 经营指标基线", "",
        "| 指标 | 数值 |", "| --- | ---: |",
        "| 已交付订单数 | {:,} |".format(metrics["delivered_orders"]),
        "| 已交付商品成交额（不含运费） | {} |".format(brl(metrics["delivered_goods_cents"])),
        "| 已交付运费 | {} |".format(brl(metrics["delivered_freight_cents"])),
        "| 商品客单价 | {} |".format(
            "{:.2f} BRL".format(metrics["delivered_goods_aov_brl"]) if metrics["delivered_goods_aov_brl"] is not None else "无有效样本"),
        "| 零运费明细数 | {} |".format(metrics["zero_freight_item_rows"]),
        "| 零运费订单数 | {} |".format(metrics["zero_freight_orders"]),
        "| 零商品金额明细数 | {} |".format(metrics["zero_price_item_rows"]),
        "| 发货截止时间缺失明细数 | {} |".format(metrics["missing_shipping_limit_rows"]), "",
        "商品客单价 = 已交付商品金额 / 已交付订单数。该基线尚未冻结最终分析区间，也尚未与支付表对账；商品成交额不能直接当作平台收入或利润。", "",
        "## 待核查与后续", "",
        "发货截止时间范围为 {} 至 {}。存在 2020 年截止记录，当前保留原值，使用该字段评估卖家时效前需结合下单日期核查。".format(
            run_info["shipping_limit_min"], run_info["shipping_limit_max"]), "",
        "实际交物流时间来自订单粒度，评价卖家时须考虑一单多卖家的归因限制。后续继续完成支付、评价等表清洗和跨表核对，以及日期范围与敏感性分析。", "",
        "原始 CSV 与已有 Notebook 保留原样；CSV 输出再次读取时需恢复日期和可空整数类型，Parquet 在环境配置阶段补充。", "",
    ])
    (report_dir / "商品明细阶段报告_v1.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
