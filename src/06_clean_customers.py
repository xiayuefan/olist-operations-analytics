"""客户阶段独立导出：在项目目录运行 python src/06_clean_customers.py。"""

import argparse
import hashlib
import json
import platform
from pathlib import Path

import pandas as pd

from customers_cleaning import (
    LOCATION_FLAG_COLS, REFERENCE_PATH, STATE_CODES,
    check_customer_locations, clean_customers, customer_field_changes,
    join_orders_customers, reconcile_customer_totals, summarize_city_orders,
    summarize_customer_identity, summarize_customer_metrics,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]


def read_source(path):
    # 邮编和 ID 按字符串读取，确保 01151 不会变成 1151。
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


def write_report(report_dir, metrics, location_check, flags, controls, city_orders, run_info):
    baseline = pd.DataFrame([
        ("客户记录数", metrics["customer_rows"]),
        ("customer_id 不同值数", metrics["customer_id_unique"]),
        ("customer_unique_id 不同值数", metrics["customer_unique_id_unique"]),
        ("对应多个客户记录的客户标识数", metrics["unique_ids_with_multiple_records"]),
        ("单个客户标识最多记录数", metrics["max_records_per_unique_id"]),
        ("关联后全部订单数", metrics["all_order_rows"]),
        ("无客户匹配订单数", metrics["orders_missing_customer"]),
        ("无订单对应客户记录数", metrics["customer_records_without_order"]),
        ("州+城市订单统计行数", metrics["city_state_order_groups"]),
        ("地区统计包含订单数", metrics["orders_in_city_state_groups"]),
        ("地区统计排除订单数", metrics["orders_excluded_from_city_state_groups"]),
    ], columns=["检查项目", "数量"])
    lines = [
        "# 客户清洗与地区订单统计阶段报告 v1", "",
        "运行：python src/06_clean_customers.py。原始客户和订单 CSV 独立读取，"
        "客户记录完整保留；当前为全量历史、全部订单状态的基线。", "",
        "## 主键、粒度与覆盖", "",
        markdown_table(baseline), "",
        "customer_id 是客户记录主键，用于与订单连接；customer_unique_id 是跨订单客户标识，"
        "可对应多个 customer_id。本次按当前文件观察到的一对一关系验证连接。"
        "2,997 这个映射计数尚未筛选有效购买状态和时间窗口，不直接解释为复购客户数。", "",
        "## 字段规范与标记", "",
        "保留原始客户记录，工作副本仅去地区字段首尾空白、统一城市小写和州大写。"
        "邮编保持字符串，不擅自补零、截断或猜测缺失地区。", "",
        markdown_table(location_check, include_index=True), "",
        markdown_table(flags.to_frame("记录数"), include_index=True), "",
        "州缩写除两位大写字母格式外，还对照 "
        "[IBGE 官方州/联邦区代码](https://servicodados.ibge.gov.br/api/v1/localidades/estados?orderBy=nome) "
        "的项目参考快照。参考代码 {} 个，校验时无需联网。"
        "邮编格式通过不等于已完成邮编、城市、州的地理一致性校验。".format(len(STATE_CODES)), "",
        "## 数量核对", "",
        markdown_table(controls, include_index=True), "",
        "订单关联后仍一行一个订单。地区表一行一个州+城市组合，"
        "通过 order_count 求和核对可分组订单数，不能要求地区表行数等于订单数。"
        "若地区不可用，完整订单仍保留，只在地区统计时排除并单独报告数量。", "",
        "## 同名城市与地区订单统计", "",
        "有 {} 个城市名称出现在多个州，因此按 customer_state 与 customer_city 组合统计。"
        "以下是全量订单计数，不是有效购买人数或已交付成交额。".format(
            metrics["city_names_across_multiple_states"]), "",
        markdown_table(city_orders.head(5)), "",
        "同名城市分州区分，城市拼写差异和邮编地理覆盖仍需后续地理表核查；"
        "本阶段没有模糊合并城市。", "",
        "## 同一客户标识的地区差异", "",
        "有 {} 个客户标识对应多个邮编值，{} 个对应多个州+城市组合，{} 个对应多个州标签。"
        "这些是字段观察，不能直接推断迁居、身份变化或具体原因。".format(
            metrics["unique_ids_with_multiple_postcodes"],
            metrics["unique_ids_with_multiple_city_states"],
            metrics["unique_ids_with_multiple_states"]), "",
        "保留每个 customer_id 的地区信息，让订单关联到各自的客户记录。"
        "不能任意按 customer_unique_id 取一条地址并覆盖所有历史订单。", "",
        "## 输出与后续", "",
        "数据目录：" + run_info["output_dir"] + "。", "",
        "输出客户工作表、订单客户关联、客户标识观察表、地区订单统计、字段变化、"
        "地区核查及多地区客户标识清单。metrics_v1.json 和 run_info_v1.json "
        "记录精确计数、来源哈希、环境和参考版本。", "",
        "下一阶段继续商品、卖家、地理和品类翻译表。复购定义、有效订单状态、正式时间窗口和"
        "地区地理一致性后续明确。当前没有计算最终复购率或将订单数当作客户人数。", "",
        "CSV 重新读取时显式保留 ID 和邮编为字符串；日期、布尔类型需按元数据恢复。"
        "Parquet、MySQL 和 Power BI 在相应阶段接入。", "",
    ]
    (report_dir / "客户阶段报告_v1.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_DIR.parent / "archive")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "data" / "processed" / "customers_v1")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_DIR / "reports" / "customers_v1")
    args = parser.parse_args()
    sources = {name: args.data_dir / name for name in [
        "olist_customers_dataset.csv", "olist_orders_dataset.csv",
    ]}
    raw = read_source(sources["olist_customers_dataset.csv"])
    orders = read_source(sources["olist_orders_dataset.csv"])

    # 顺序与课堂一致：工作副本 -> 关联订单 -> 地区聚合 -> 数量核对。
    cleaned = clean_customers(raw)
    joined = join_orders_customers(orders, cleaned)
    city_orders = summarize_city_orders(joined)
    identities = summarize_customer_identity(cleaned)
    controls = reconcile_customer_totals(orders, cleaned, joined, city_orders)
    metrics = summarize_customer_metrics(raw, cleaned, joined, city_orders, identities)
    location_check = check_customer_locations(raw, cleaned)
    changes = customer_field_changes(raw, cleaned)
    flags = cleaned[LOCATION_FLAG_COLS + ["flag_customer_location_needs_review"]].sum()
    key_check = pd.Series({
        "客户记录数": len(raw), "customer_id不同值数": raw["customer_id"].nunique(),
        "customer_unique_id不同值数": raw["customer_unique_id"].nunique(),
        "customer_id缺失数": raw["customer_id"].isna().sum(),
        "customer_unique_id缺失数": raw["customer_unique_id"].isna().sum(),
        "customer_id重复行数_首条之后": raw["customer_id"].duplicated().sum(),
        "customer_unique_id重复行数_首条之后": raw["customer_unique_id"].duplicated().sum(),
        "整行重复数_首条之后": raw.duplicated().sum(),
    })
    city_states = cleaned.groupby("customer_city")["customer_state"].nunique()

    # 所有输入检查与控制总额通过后，再写入本阶段独立目录。
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    for filename, frame in [
        ("customers_clean_v1.csv", cleaned), ("orders_with_customers_v1.csv", joined),
        ("customer_identity_summary_v1.csv", identities),
    ]:
        frame.to_csv(args.output_dir / filename, index=False, encoding="utf-8-sig")
    tables = [
        ("city_order_counts_v1.csv", city_orders),
        ("customer_field_changes_v1.csv", changes),
        ("location_needs_review_v1.csv", cleaned.loc[cleaned["flag_customer_location_needs_review"]]),
        ("unused_customer_records_v1.csv", cleaned.loc[~cleaned["customer_id"].isin(orders["customer_id"])]),
        ("customer_identity_multiple_locations_v1.csv", identities.loc[
            identities["postcode_count"].gt(1) | identities["city_state_count"].gt(1)]),
        ("customer_identity_multiple_states_v1.csv", identities.loc[identities["state_count"].gt(1)]),
        ("city_names_in_multiple_states_v1.csv",
         city_states.loc[city_states.gt(1)].rename_axis("customer_city").reset_index(name="州标签数")),
        ("customer_record_count_distribution_v1.csv",
         identities["customer_record_count"].value_counts().sort_index().rename_axis(
             "每个客户标识对应记录数").reset_index(name="客户标识数")),
    ]
    for filename, frame in tables:
        frame.to_csv(args.report_dir / filename, index=False, encoding="utf-8-sig")
    for filename, frame in [
        ("customer_key_check_v1.csv", key_check.to_frame("数量")),
        ("customer_location_check_v1.csv", location_check),
        ("customer_location_flags_v1.csv", flags.to_frame("记录数")),
        ("customer_control_totals_v1.csv", controls),
    ]:
        frame.to_csv(args.report_dir / filename, index_label="检查项", encoding="utf-8-sig")

    run_info = {
        "version": "customers_v1", "source_dir": str(args.data_dir.resolve()),
        "source_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sources.items()},
        "python": platform.python_version(), "pandas": pd.__version__,
        "input_customer_rows": len(raw), "output_customer_rows": len(cleaned), "deleted_customer_rows": 0,
        "input_order_rows": len(orders), "output_order_rows": len(joined),
        "output_dir": str(args.output_dir.resolve()),
        "state_reference": str(REFERENCE_PATH),
        "state_reference_sha256": hashlib.sha256(REFERENCE_PATH.read_bytes()).hexdigest(),
        "state_reference_url": "https://servicodados.ibge.gov.br/api/v1/localidades/estados?orderBy=nome",
        "record_grain": "客户表 customer_id 一行；标识观察表 customer_unique_id 一行",
        "scope": "全量历史、全部订单状态的客户覆盖和地区订单计数",
        "city_grouping": ["customer_state", "customer_city"],
        "missing_or_invalid_locations": "保留客户/订单记录并标记；州城市统计只用可分组记录",
        "zip_policy": "字符串、五位数字格式检查；保留前导零，不猜测补零",
        "pending_checks": [
            "邮编与地理表覆盖、城市拼写和地区一致性", "客户标识多地区值的业务原因",
            "有效购买状态、时间范围、复购定义与观察窗口", "其他表、Parquet、MySQL 和 Power BI",
        ],
    }
    for filename, payload in [("metrics_v1.json", metrics), ("run_info_v1.json", run_info)]:
        (args.report_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    write_report(args.report_dir, metrics, location_check, flags, controls, city_orders, run_info)
    print("客户记录：{}；客户标识：{}；关联后订单：{}".format(
        metrics["customer_rows"], metrics["customer_unique_id_unique"], metrics["all_order_rows"]))
    print("州城市组合：{}；地区订单合计：{}；地区待核查记录：{}".format(
        metrics["city_state_order_groups"], metrics["orders_in_city_state_groups"], metrics["location_review_rows"]))
    print("报告目录：" + str(args.report_dir.resolve()))


if __name__ == "__main__":
    main()
