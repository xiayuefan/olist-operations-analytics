"""独立导出评价阶段：在项目目录运行 python src/05_clean_reviews.py。"""

import argparse
import hashlib
import json
import platform
from pathlib import Path

import pandas as pd

from reviews_cleaning import (
    aggregate_order_reviews, check_review_dates, check_review_keys, check_review_text,
    clean_order_reviews, compare_review_rules, join_orders_reviews,
    reconcile_review_totals, select_latest_reviews, summarize_review_metrics,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]


def read_source(path):
    # 字符串读取保留 ID、原始日期和评论；空字段识别为缺失值。
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


def write_report(report_dir, metrics, key_check, text_check, date_check,
                 controls, comparison, missing_status, sample, run_info):
    baseline = pd.DataFrame([
        ("评价记录数", metrics["review_rows"]),
        ("有有效评价订单数", metrics["reviewed_orders"]),
        ("多评订单数", metrics["multi_review_orders"]),
        ("低评分评价记录数", metrics["low_score_review_rows"]),
        ("任意一次低评分订单数", metrics["any_low_score_orders"]),
        ("最新有效评分为低分的订单数", metrics["latest_low_score_orders"]),
        ("两种规则判定不同的订单数", metrics["rules_disagree_orders"]),
        ("主表订单数", metrics["all_order_rows"]),
        ("无评价订单数", metrics["orders_without_reviews"]),
        ("其中已交付订单数", metrics["delivered_without_reviews"]),
    ], columns=["指标", "数量"])
    lines = [
        "# 评价清洗与订单级规则阶段报告 v1", "",
        "运行：python src/05_clean_reviews.py。从原始评价、订单 CSV 独立复现；"
        "评价明细保留，订单级结果另表生成。", "",
        "## 当前范围与主口径", "",
        "当前为全量历史、全部订单状态的课堂基线。项目定义 1～2 分为低评分。"
        "订单主口径采用最新有效评分，对照口径采用任意一次低评分。"
        "最新指当前文件中客户提交时间最大的记录，不代表客户未来不会再评价。", "",
        markdown_table(baseline), "",
        "## 主键与粒度", "",
        markdown_table(key_check.to_frame(), include_index=True), "",
        "review_id、order_id 单列均不唯一，组合键非空且唯一。"
        "多评记录不是整行重复，不按单列删除。明细一行一条评价，"
        "最新评价表和评价汇总表一行一个订单；主表关联后保留全部订单。", "",
        "## 评分、文字和时间", "",
        "评分须是非空的 1～5 整数。没有文字不等于评分无效。"
        "文字字段保留原值，仅额外生成是否存在非空白文字的标记。", "",
        markdown_table(text_check, include_index=True), "",
        "review_creation_date 是问卷创建、发送日期，review_answer_timestamp 是客户提交时间。", "",
        markdown_table(date_check, include_index=True), "",
        "提交早于创建的记录数为 {}。最大提交间隔为 {} 天。"
        "间隔包含等待时间，不是填写问卷用时；长间隔保留并另列原始样本待核查。".format(
            metrics["answer_before_creation_rows"],
            "{:.2f}".format(metrics["max_answer_lag_days"])
            if metrics["max_answer_lag_days"] is not None else "未知"), "",
        "## 最新评价与聚合的具体位置", "",
        "select_latest_reviews 先用 groupby + transform(max) 找每单最大提交时间，"
        "再由 loc 筛选对应记录。最新时间并列、提交时间缺失或出现倒置时停止核查，"
        "不任意取第一行。缺少问卷创建日期会影响间隔计算，已知提交时间仍可用于排序。", "",
        "aggregate_order_reviews 用 groupby + agg 把全部评价聚合成订单。size 统计记录数，"
        "sum 统计低评分记录数，any 判断是否出现过低评分；再连接每单最新评价。"
        "validate='one_to_one' 只检查唯一性，实际筛选和聚合发生在前两步。", "",
        "## 控制总额", "",
        markdown_table(controls, include_index=True), "",
        "聚合后行数减少，但评价记录数量、低评分记录数量可以通过汇总计数列追溯，"
        "不能将选取最新评价理解为删除了原始明细。", "",
        "## 两种规则的对照", "",
        markdown_table(comparison, include_index=True), "",
        "低评分评价记录有 {:,} 条，至少一次低分的订单有 {:,} 笔；"
        "其中 {} 笔订单有多条低分记录，贡献 {} 条首条之后的低分记录。"
        "这属于记录与订单粒度的区别。".format(
            metrics["low_score_review_rows"], metrics["any_low_score_orders"],
            metrics["orders_with_multiple_low_reviews"], metrics["extra_low_review_rows"]), "",
        "规则判定不同的 {} 笔订单，反映主口径与对照口径的差别；"
        "不能仅凭后一次评分提高就认定运营干预有效。".format(metrics["rules_disagree_orders"]), "",
    ]
    if run_info["rule_disagreement_sample_order_id"] is not None:
        lines.extend([
            "样本订单：" + run_info["rule_disagreement_sample_order_id"] + "。", "",
            markdown_table(sample), "",
        ])
    lines.extend([
        "## 覆盖与缺失状态", "",
        markdown_table(missing_status), "",
        "无评价订单的最新评分、最新低分标记、任意低分标记均保持未知。"
        "False 表示有有效评价且该规则判定为非低分，不能用来填补无评价订单。"
        "当前低评分比例以有有效评价订单为分母，缺失数量另报。", "",
        "## 待完成工作", "",
        "重复评价 ID 跨订单的业务原因、长提交间隔原因仍需核查。"
        "正式分析状态和时间窗口、客户/商品/卖家/地理维表、Parquet、MySQL 和 Power BI 尚待后续阶段。"
        "若分析某个历史时点，应限制评价可见时间；当前全量最近评分不等同于当时已知的评分。", "",
        "导出 CSV 再次读取时恢复 Int64、boolean、日期类型，并使用正确的缺失解析规则。"
        "元数据、指标和来源哈希分别见 run_info_v1.json、metrics_v1.json。", "",
    ])
    (report_dir / "评价阶段报告_v1.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_DIR.parent / "archive")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "data" / "processed" / "reviews_v1")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_DIR / "reports" / "reviews_v1")
    args = parser.parse_args()
    sources = {
        name: args.data_dir / name
        for name in ["olist_order_reviews_dataset.csv", "olist_orders_dataset.csv"]
    }
    raw_reviews = read_source(sources["olist_order_reviews_dataset.csv"])
    raw_orders = read_source(sources["olist_orders_dataset.csv"])

    # 顺序与课堂完全对应：保留明细 -> 选最新 -> 聚合 -> 关联 -> 核对。
    cleaned = clean_order_reviews(raw_reviews)
    latest = select_latest_reviews(cleaned)
    summary = aggregate_order_reviews(cleaned, latest)
    joined = join_orders_reviews(raw_orders, summary)
    controls = reconcile_review_totals(cleaned, latest, summary, joined)
    metrics = summarize_review_metrics(cleaned, latest, summary, joined)
    comparison = compare_review_rules(summary)
    key_check = check_review_keys(raw_reviews)
    text_check = check_review_text(raw_reviews)
    date_check = check_review_dates(raw_reviews, cleaned)

    missing = joined.loc[joined["flag_missing_reviews"]].copy()
    missing_status = missing["order_status"].value_counts().rename_axis("order_status").reset_index(name="订单数")
    disagreements = summary.loc[summary["rules_disagree"]].sort_values("order_id")
    sample_id = disagreements.iloc[0]["order_id"] if len(disagreements) else None
    sample = cleaned.loc[cleaned["order_id"].eq(sample_id), [
        "order_id", "review_id", "review_score", "review_answer_timestamp",
    ]].sort_values("review_answer_timestamp")

    # 所有检查通过才写输出；旧的订单、商品、支付阶段目录不参与本次写入。
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    for filename, frame in [
        ("reviews_clean_v1.csv", cleaned), ("latest_reviews_v1.csv", latest),
        ("order_reviews_v1.csv", summary), ("orders_with_reviews_v1.csv", joined),
    ]:
        frame.to_csv(args.output_dir / filename, index=False, encoding="utf-8-sig")

    low_counts = cleaned.loc[cleaned["is_low_score"], "order_id"].value_counts()
    low_distribution = low_counts.value_counts().sort_index().rename_axis(
        "每单低评分记录数").reset_index(name="订单数")
    report_tables = [
        ("missing_reviews_v1.csv", missing),
        ("missing_reviews_by_status_v1.csv", missing_status),
        ("rules_disagreements_v1.csv", disagreements),
        ("rules_disagreement_raw_reviews_v1.csv",
         cleaned.loc[cleaned["order_id"].isin(disagreements["order_id"])]),
        ("rule_disagreement_sample_v1.csv", sample),
        ("multi_review_orders_v1.csv", summary.loc[summary["review_record_count"].gt(1)]),
        ("repeated_review_ids_v1.csv", cleaned.loc[cleaned["review_id"].duplicated(keep=False)]),
        ("largest_review_lags_v1.csv", cleaned.nlargest(5, "review_answer_lag_days")),
        ("low_score_records_per_order_v1.csv", low_distribution),
        ("review_score_counts_v1.csv", cleaned["review_score"].value_counts().sort_index().rename_axis(
            "review_score").reset_index(name="评价记录数")),
    ]
    for filename, frame in report_tables:
        frame.to_csv(args.report_dir / filename, index=False, encoding="utf-8-sig")
    for filename, frame in [
        ("review_key_check_v1.csv", key_check.to_frame()),
        ("review_text_check_v1.csv", text_check), ("review_date_check_v1.csv", date_check),
        ("review_control_totals_v1.csv", controls), ("rule_comparison_v1.csv", comparison),
    ]:
        frame.to_csv(args.report_dir / filename, index_label="检查项", encoding="utf-8-sig")

    run_info = {
        "version": "reviews_v1",
        "source_dir": str(args.data_dir.resolve()),
        "source_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sources.items()},
        "python": platform.python_version(), "pandas": pd.__version__,
        "input_review_rows": len(raw_reviews), "output_clean_review_rows": len(cleaned),
        "deleted_review_rows": 0,
        "input_order_rows": len(raw_orders), "output_order_rows": len(joined),
        "scope": "全量历史、全部状态，有有效评价的订单用于当前比例基线",
        "low_score_rule": "review_score <= 2（仅 1 或 2 分）",
        "primary_order_rule": "每单最大 review_answer_timestamp 对应的有效评分",
        "comparison_order_rule": "每单任意一次有效评分 <= 2",
        "latest_tie_policy": "同订单最新提交时间并列时停止，需明确规则",
        "missing_or_reversed_answer_policy": "保留明细，选择最新评价前停止核查，不猜测时间",
        "missing_review_policy": "订单保留，评分和布尔标记未知，不填 False",
        "rule_disagreement_sample_order_id": sample_id,
        "output_dir": str(args.output_dir.resolve()),
        "csv_types": "恢复 Int64、boolean 和日期；读取原始字符串时 keep_default_na=False, na_values=['']",
        "pending_checks": [
            "评价 ID 跨订单复用的业务原因", "长问卷提交间隔原因",
            "正式状态、日期和评价可见性窗口", "其他维表、Parquet、MySQL 和 Power BI",
        ],
    }
    for filename, payload in [("metrics_v1.json", metrics), ("run_info_v1.json", run_info)]:
        (args.report_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    write_report(args.report_dir, metrics, key_check, text_check, date_check,
                 controls, comparison, missing_status, sample, run_info)
    print("评价明细：{}；订单级结果：{}；关联后订单：{}".format(
        metrics["review_rows"], metrics["reviewed_orders"], metrics["all_order_rows"]))
    print("最新低分订单：{}；任意低分订单：{}；规则不同：{}；无评价订单：{}".format(
        metrics["latest_low_score_orders"], metrics["any_low_score_orders"],
        metrics["rules_disagree_orders"], metrics["orders_without_reviews"]))
    print("报告目录：" + str(args.report_dir.resolve()))


if __name__ == "__main__":
    main()
