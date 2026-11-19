"""从三张原始 CSV 独立复现支付阶段：python src/04_clean_payments.py。"""

import argparse
import hashlib
import json
import platform
from pathlib import Path

import pandas as pd

from items_cleaning import aggregate_order_items, clean_order_items, reconcile_item_totals
from payments_cleaning import (
    aggregate_order_payments, amount_difference_distribution, clean_order_payments,
    join_orders_payments, reconcile_order_amounts, reconcile_payment_totals,
    recheck_raw_order, summarize_payment_metrics,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]


def read_source(path):
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig",
                       keep_default_na=False, na_values=[""])


def markdown_table(frame, include_index=False):
    table = frame.reset_index() if include_index else frame
    def cell(value):
        if pd.isna(value):
            return "缺失"
        return str(value).replace("|", r"\|").replace("\n", " ")
    lines = [
        "| " + " | ".join(map(str, table.columns)) + " |",
        "| " + " | ".join(["---"] * len(table.columns)) + " |",
    ]
    for row in table.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(cell(value) for value in row) + " |")
    return "\n".join(lines)


def write_report(report_dir, metrics, controls, distribution, missing, by_status, case, run_info):
    scope = pd.DataFrame([
        ("支付记录数", metrics["payment_rows"]),
        ("支付覆盖订单数", metrics["orders_with_payments"]),
        ("订单主表行数", metrics["all_order_rows"]),
        ("多条支付记录订单数", metrics["multi_payment_orders"]),
        ("零金额支付记录数", metrics["zero_payment_rows"]),
        ("含零金额支付记录的订单数", metrics["orders_with_zero_payment_record"]),
        ("支付总额为零的订单数", metrics["zero_payment_total_orders"]),
        ("支付方式未定义记录数", metrics["undefined_type_rows"]),
        ("分期期数为零记录数", metrics["zero_installment_rows"]),
        ("上述记录标记的并集行数", metrics["flagged_payment_rows"]),
    ], columns=["检查项目", "数量"])
    comparison = pd.DataFrame([
        ("可核对订单", metrics["amount_comparable_orders"]),
        ("无法核对订单", metrics["amount_uncomparable_orders"]),
        ("缺少商品明细订单", metrics["orders_missing_items"]),
        ("缺少支付记录订单", metrics["orders_missing_payments"]),
        ("金额完全一致订单", metrics["amount_equal_orders"]),
        ("存在金额差额订单", metrics["amount_mismatch_orders"]),
    ], columns=["检查项目", "订单数"])
    missing_cols = ["order_id", "order_status", "order_purchase_timestamp", "payment_amount_cents"]
    missing_cols = [col for col in missing_cols if col in missing.columns]
    sections = [
        "# 支付清洗与跨表金额核对阶段报告 v1", "",
        "运行：python src/04_clean_payments.py。三个输入文件从原始 CSV 读取；商品清洗与聚合复用上一阶段函数。", "",
        "## 处理范围与口径", "",
        "保留全部原始订单、商品明细和支付记录。支付组合键为 order_id + payment_sequential；"
        "payment_installments 是每条记录的期数，payment_value 是该记录总额，金额不乘期数。", "",
        "金额从原始字符串精确换算为整数分，BRL 展示时除以 100。主键、金额解析、负值或外键覆盖错误会停止流程；"
        "零金额、not_defined、零期数及跨表差额保留并记录核查标记。零期数含义尚未核实。", "",
        markdown_table(scope), "",
        "支付方式标签数按支付记录统计。含零金额记录不等于整笔订单支付额为零。"
        "缺少支付记录的金额及订单级支付特征保持未知。", "",
        "## 汇总与关联控制总额", "",
        "支付记录数量和支付金额在明细、订单汇总、关联后的三个层次核对；下面两个差额列须全部为零。", "",
        markdown_table(controls, include_index=True), "",
        "商品侧另输出 item_control_totals_v1.csv，核对商品明细数量、商品金额和运费。", "",
        "## 支付覆盖", "",
        "左右两侧订单键均唯一，并在左连接前反向检查支付订单 ID 全部能在主表找到。", "",
        markdown_table(missing[missing_cols]), "",
        "缺少支付记录只能说明本数据无法提供支付金额，不能认定未付款；不填为零。", "",
        "## 订单金额核对", "",
        "差额 = 支付金额 -（商品金额 + 运费）。三项金额全部非空才可核对；"
        "差额为零才定义为完全一致，无法核对时差额与差额标记均保持未知。", "",
        markdown_table(comparison), "",
        "## 差额分布", "",
        markdown_table(distribution), "",
        "方向和大小是两种独立划分。大小分组用于描述分布，不构成核对容差；1 分差异仍保留。"
        "未获得业务凭据前，不能将差异直接解释为多收、漏收、手续费、折扣或损失。", "",
        "有差额订单按当前状态统计如下；这些是历史数据的当前状态，不代表支付事件时的状态。", "",
        markdown_table(by_status), "",
        "## 原始记录样本复核", "",
    ]
    if run_info["sample_order_id"] is not None:
        sections.extend([
            "按绝对差额最大优先选取订单：" + run_info["sample_order_id"] + "。", "",
            markdown_table(case, include_index=True), "",
            "差值全部为零，说明这笔样本的原始 CSV 中已经存在相同的跨表金额差异，"
            "当前汇总与关联没有新增该样本差额。此结论只对应已复核样本，其业务原因仍待核查。"
            "原始商品及支付样本分别保存于 case_items_v1.csv、case_payments_v1.csv。", "",
        ])
    else:
        sections.extend(["当前输入没有金额差额样本，未执行最大差额订单复核。", ""])
    sections.extend([
        "## 输出与后续", "",
        "数据输出目录：" + run_info["output_dir"] + "。", "",
        "完整差额清单、无法核对清单、支付记录核查清单及前五大差额均单独导出。"
        "metrics_v1.json 保存整数指标；run_info_v1.json 保存来源哈希、环境、口径和待核查事项。", "",
        "本阶段为全量历史、全部状态的金额一致性核查；支付记录金额不等同于已交付商品成交额、平台收入或利润。"
        "正式分析区间、差额原因与敏感性分析、退款和其他业务凭据仍需后续处理。", "",
        "CSV 不携带可空整数、布尔和日期类型；重新读取需显式恢复。"
        "Parquet 与项目环境配置、评价和其他维表、MySQL 及 Power BI 仍属后续工作。", "",
    ])
    (report_dir / "支付阶段报告_v1.md").write_text("\n".join(sections), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_DIR.parent / "archive")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "data" / "processed" / "payments_v1")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_DIR / "reports" / "payments_v1")
    args = parser.parse_args()
    filenames = [
        "olist_order_payments_dataset.csv", "olist_orders_dataset.csv", "olist_order_items_dataset.csv",
    ]
    sources = {name: args.data_dir / name for name in filenames}
    raw_payments = read_source(sources[filenames[0]])
    raw_orders = read_source(sources[filenames[1]])
    raw_items = read_source(sources[filenames[2]])

    cleaned = clean_order_payments(raw_payments)
    summary = aggregate_order_payments(cleaned)
    joined = join_orders_payments(raw_orders, summary)
    payment_controls = reconcile_payment_totals(cleaned, summary, joined)
    cleaned_items = clean_order_items(raw_items)
    item_summary = aggregate_order_items(cleaned_items)
    reconciled = reconcile_order_amounts(joined, item_summary)
    item_controls = reconcile_item_totals(cleaned_items, item_summary, reconciled)
    metrics = summarize_payment_metrics(cleaned, summary, reconciled)
    distribution = amount_difference_distribution(reconciled)
    missing = reconciled.loc[reconciled["flag_missing_payments"]].copy()
    mismatches = reconciled.loc[reconciled["flag_amount_mismatch"].fillna(False)].copy()
    top = mismatches.nlargest(5, "abs_difference_cents")
    by_status = mismatches["order_status"].value_counts().rename_axis("order_status").reset_index(name="订单数")
    sample_id = top.iloc[0]["order_id"] if len(top) else None
    case = recheck_raw_order(raw_items, raw_payments, reconciled, sample_id) if sample_id else pd.DataFrame(
        columns=["原始明细重算", "订单级结果", "差值"])

    # 所有输入校验、控制总额和样本复核通过后再输出。
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in [
        ("payments_clean_v1.csv", cleaned), ("order_payment_summary_v1.csv", summary),
        ("orders_with_payments_v1.csv", joined), ("orders_amount_check_v1.csv", reconciled),
    ]:
        frame.to_csv(args.output_dir / name, index=False, encoding="utf-8-sig")
    type_counts = cleaned["payment_type"].value_counts().rename_axis("payment_type").reset_index(name="支付记录数")
    report_tables = [
        ("missing_payments_v1.csv", missing),
        ("amount_uncomparable_v1.csv", reconciled.loc[~reconciled["can_reconcile_amount"]]),
        ("amount_mismatches_v1.csv", mismatches),
        ("top_amount_differences_v1.csv", top),
        ("payment_records_needing_review_v1.csv", cleaned.loc[cleaned["flag_payment_needs_review"]]),
        ("payment_type_counts_v1.csv", type_counts),
        ("amount_difference_distribution_v1.csv", distribution),
        ("amount_mismatches_by_status_v1.csv", by_status),
        ("case_items_v1.csv", raw_items.loc[raw_items["order_id"].eq(sample_id)]),
        ("case_payments_v1.csv", raw_payments.loc[raw_payments["order_id"].eq(sample_id)]),
    ]
    for name, frame in report_tables:
        frame.to_csv(args.report_dir / name, index=False, encoding="utf-8-sig")
    for name, frame in [
        ("payment_control_totals_v1.csv", payment_controls),
        ("item_control_totals_v1.csv", item_controls), ("case_recheck_v1.csv", case),
    ]:
        frame.to_csv(args.report_dir / name, encoding="utf-8-sig", index_label="检查项")

    run_info = {
        "version": "payments_v1",
        "source_dir": str(args.data_dir.resolve()),
        "source_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sources.items()},
        "output_dir": str(args.output_dir.resolve()),
        "python": platform.python_version(), "pandas": pd.__version__,
        "input_payment_rows": len(raw_payments), "output_payment_rows": len(cleaned),
        "input_order_rows": len(raw_orders), "output_order_rows": len(reconciled),
        "input_item_rows": len(raw_items), "deleted_rows": 0,
        "money_unit": "整数分；BRL 展示时除以 100",
        "scope": "全量历史、全部状态；用于跨表金额一致性核查",
        "difference_formula": "payment_amount_cents - goods_amount_cents - freight_amount_cents",
        "exact_match_rule": "三项金额非空且差额为零；分组不作容差",
        "sample_order_id": sample_id,
        "csv_types": "重读时恢复整数分 Int64、可空 boolean 和日期字段",
        "pending_checks": [
            "零期数业务含义", "跨表金额差异及缺少支付记录的业务原因",
            "退款及其他业务凭据在当前原始表中未提供，不能据差额推断",
            "正式分析区间与异常记录敏感性分析", "其余表清洗、Parquet、MySQL 与 Power BI",
        ],
    }
    for name, payload in [("metrics_v1.json", metrics), ("run_info_v1.json", run_info)]:
        (args.report_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    write_report(args.report_dir, metrics, payment_controls, distribution, missing, by_status, case, run_info)
    print("支付记录：{}；支付覆盖订单：{}；主表订单：{}".format(
        metrics["payment_rows"], metrics["orders_with_payments"], metrics["all_order_rows"]))
    print("可核对：{}；完全一致：{}；有差额：{}；无法核对：{}".format(
        metrics["amount_comparable_orders"], metrics["amount_equal_orders"],
        metrics["amount_mismatch_orders"], metrics["amount_uncomparable_orders"]))
    print("报告目录：" + str(args.report_dir.resolve()))


if __name__ == "__main__":
    main()
