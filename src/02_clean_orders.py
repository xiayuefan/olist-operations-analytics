"""运行指定版本的订单整理，并保存课堂结果。

从项目根目录运行：python .\src\02_clean_orders.py
八规则版本：python .\src\02_clean_orders.py --rules-version v2
"""

import argparse
import json
import platform
from pathlib import Path

import pandas as pd

from orders_cleaning import (
    clean_orders, get_review_flag_cols, summarize_metrics, summarize_rule_coverage,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_DIR.parent / "archive")
    parser.add_argument("--rules-version", choices=["v1", "v2"], default="v1")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args()
    version = args.rules_version
    output_dir = args.output_dir or PROJECT_DIR / "data" / "processed" / ("orders_" + version)
    report_dir = args.report_dir or PROJECT_DIR / "reports" / ("orders_" + version)
    flag_cols = get_review_flag_cols(version)
    source = (args.data_dir / "olist_orders_dataset.csv").resolve()
    raw = pd.read_csv(source, dtype=str, encoding="utf-8-sig", keep_default_na=False, na_values=[""])
    cleaned = clean_orders(raw, rules_version=version)
    metrics = summarize_metrics(cleaned, rules_version=version)
    coverage = summarize_rule_coverage(cleaned, rules_version=version)

    output_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(output_dir / ("orders_clean_" + version + ".csv"), index=False, encoding="utf-8-sig")
    review_cols = list(raw.columns) + flag_cols + ["review_rule_count"]
    cleaned.loc[cleaned["flag_needs_review"], review_cols].to_csv(
        report_dir / ("orders_review_" + version + ".csv"), index=False, encoding="utf-8-sig")
    cleaned[flag_cols].sum().rename_axis("rule").reset_index(name="orders").to_csv(
        report_dir / ("quality_summary_" + version + ".csv"), index=False, encoding="utf-8-sig")
    coverage.to_csv(report_dir / ("rule_coverage_" + version + ".csv"), index=False, encoding="utf-8-sig")
    (report_dir / ("metrics_" + version + ".json")).write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (report_dir / ("run_info_" + version + ".json")).write_text(json.dumps({
        "source": str(source), "python": platform.python_version(), "pandas": pd.__version__,
        "rules_version": version, "review_rule_count": len(flag_cols),
        "rows_kept": len(cleaned), "rows_deleted": 0,
        "metrics_scope_version": "课堂基线：运输和延迟各用自己的有效样本条件",
        "scope": "全量原始订单的课堂基线，尚未冻结最终分析区间",
        "time_storage": "CSV 不保存时间类型，重新读取时需转换五个时间字段",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(report_dir, version, source, cleaned, coverage, metrics)
    print("保留订单：{}；规则触发次数：{}；待核查订单：{}".format(
        metrics["order_rows"], metrics["review_rule_hits"], metrics["review_orders"]))
    print("运输有效样本：{}；延迟有效样本：{}；延迟订单：{}".format(
        metrics["valid_transit_orders"], metrics["valid_delay_orders"], metrics["late_orders"]))
    print("规则版本：{}；结果目录：{}".format(version, report_dir.resolve()))


def write_report(report_dir, version, source, cleaned, coverage, metrics):
    """把本次运行的实际结果写成可复核的 Markdown 报告。"""
    def fmt(value, percent=False):
        if value is None:
            return "无有效样本"
        return "{:.2%}".format(value) if percent else "{:.2f}".format(value)

    lines = [
        "# 订单表清洗阶段报告 " + version, "",
        "输入：`{}`。由 `src/02_clean_orders.py --rules-version {}` 生成。".format(source, version), "",
        "## 规则范围与记录保留", "",
        "本版使用 {} 条核查规则。输入、输出均为 {:,} 笔订单，未删除记录，也未填补缺失时间。".format(len(coverage), len(cleaned)), "",
        "规则合计触发 {:,} 次，涉及 {:,} 笔不同订单。核查清单不代表已确认错误，未触发也不代表通过所有可能的检查。".format(metrics["review_rule_hits"], metrics["review_orders"]), "",
        "| 规则 | 适用订单数 | 不在适用范围 | 触发订单数 | 适用范围 |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in coverage.to_dict(orient="records"):
        lines.append("| {rule} | {eligible_orders:,} | {outside_scope_orders:,} | {flagged_orders:,} | {scope} |".format(**row))
    lines.extend([
        "", "时间比较规则需要两端有值，缺失任一端时无法进行该比较；状态类规则的适用范围由状态确定。", "",
        "## 指标初算", "",
        "| 指标 | 数值 |", "| --- | ---: |",
        "| 运输有效样本数 | {:,} |".format(metrics["valid_transit_orders"]),
        "| 平均运输天数 | {} |".format(fmt(metrics["transit_mean_days"])),
        "| 运输 P50 / P90（天） | {} / {} |".format(fmt(metrics["transit_p50_days"]), fmt(metrics["transit_p90_days"])),
        "| 运输 P95 / P99（天） | {} / {} |".format(fmt(metrics["transit_p95_days"]), fmt(metrics["transit_p99_days"])),
        "| 最大运输天数 | {} |".format(fmt(metrics["transit_max_days"])),
        "| 延迟有效样本数 | {:,} |".format(metrics["valid_delay_orders"]),
        "| 延迟订单数 | {:,} |".format(metrics["late_orders"]),
        "| 延迟率 | {} |".format(fmt(metrics["late_rate"], percent=True)), "",
        "运输为实际经过秒数除以 86400；延迟按实际送达日期减预计送达日期，大于零为延迟。两者各有自己的有效样本条件。", "",
        "v2 增加审批相关的核查规则，当前运输和延迟指标的样本条件仍沿用课堂基线；核查范围扩大不等于所有指标都应统一删除更多记录。", "",
        "## 重复命中", "",
        "| 单笔订单触发规则数 | 订单数 |", "| ---: | ---: |",
    ])
    for hits, count in cleaned["review_rule_count"].value_counts().sort_index().items():
        lines.append("| {} | {:,} |".format(hits, count))
    lines.extend([
        "", "## 解释与下一步", "",
        "交物流早于审批是记录层面的顺序核查线索，不能据此确定未付款发货或具体原因。长耗时但顺序合理的记录继续保留，P99 不作为删除阈值。", "",
        "当前覆盖全量历史订单，尚未冻结最终分析区间。后续补充异常记录敏感性分析、其他表清洗、关联与金额核对。", "",
        "CSV 不保留 Pandas 时间类型；原始 CSV 保留原样，已输出的工作表再次读取时需转换日期。", "",
    ])
    (report_dir / ("订单清洗报告_" + version + ".md")).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
