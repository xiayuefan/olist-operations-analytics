"""客户阶段 v1：保留客户记录、地区规范、订单关联和地区计数。

customer_id 是记录主键；customer_unique_id 是跨订单客户标识。
不按 customer_unique_id 删除记录，不把多条记录直接解释为复购。
兼容 Python 3.7+ / Pandas 1.1+。
"""

import json
from pathlib import Path

import pandas as pd

from orders_cleaning import ORDER_STATUSES


CUSTOMER_COLS = [
    "customer_id", "customer_unique_id", "customer_zip_code_prefix",
    "customer_city", "customer_state",
]
LOCATION_COLS = ["customer_zip_code_prefix", "customer_city", "customer_state"]
LOCATION_FLAG_COLS = [
    "flag_zip_format_invalid", "flag_state_format_invalid",
    "flag_state_unknown", "flag_city_missing",
]
REFERENCE_PATH = Path(__file__).resolve().parents[1] / "docs" / "references" / "ibge_state_codes_v1.json"
# 读取已核对的官方参考快照；运行时不依赖联网。
STATE_CODES = frozenset(json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))["state_codes"])


def _require_columns(frame, cols, label):
    missing = sorted(set(cols) - set(frame.columns))
    if missing:
        raise ValueError(label + "缺少列：" + ", ".join(missing))
    if frame.empty:
        raise ValueError(label + "为空，请核查输入")


def _check_nonblank(frame, col, label):
    if frame[col].isna().any() or frame[col].astype(str).str.strip().eq("").any():
        raise ValueError(label + "存在缺失或空白：" + col)
    if frame[col].astype(str).ne(frame[col].astype(str).str.strip()).any():
        raise ValueError(label + "标识符含首尾空白，请核查后再关联：" + col)


def _check_primary_key(frame, col, label):
    _require_columns(frame, [col], label)
    _check_nonblank(frame, col, label)
    if frame[col].duplicated().any():
        raise ValueError(label + "主键重复：" + col)


def clean_customers(raw_customers):
    """返回工作副本，规范地区格式并保留待核查标记，不删除客户记录。"""
    _require_columns(raw_customers, CUSTOMER_COLS, "客户原表")
    _check_primary_key(raw_customers, "customer_id", "客户原表")
    _check_nonblank(raw_customers, "customer_unique_id", "客户原表")
    cleaned = raw_customers.copy()

    # ID 不作大小写、补零等猜测。地区字段只去首尾空白并规范大小写。
    # 邮编保持字符串；遇到 1151 只标记，不擅自补成 01151。
    for col in LOCATION_COLS:
        if not raw_customers[col].dropna().map(lambda value: isinstance(value, str)).all():
            raise ValueError("地区字段请从原始 CSV 按字符串读取：" + col)
        cleaned[col] = raw_customers[col].str.strip()
    cleaned["customer_city"] = cleaned["customer_city"].str.lower()
    cleaned["customer_state"] = cleaned["customer_state"].str.upper()

    # 格式规则与取值规则分开：AA 符合两位字母格式，但不在官方代码表里。
    cleaned["flag_zip_format_invalid"] = ~cleaned["customer_zip_code_prefix"].str.fullmatch(
        "[0-9]{5}", na=False)
    cleaned["flag_state_format_invalid"] = ~cleaned["customer_state"].str.fullmatch(
        "[A-Z]{2}", na=False)
    cleaned["flag_state_unknown"] = ~cleaned["customer_state"].isin(STATE_CODES)
    cleaned["flag_city_missing"] = (
        cleaned["customer_city"].isna() | cleaned["customer_city"].eq(""))
    cleaned["flag_customer_location_needs_review"] = cleaned[LOCATION_FLAG_COLS].any(axis=1)

    # 州+城市统计不需要邮编参与：邮编有问题时，仍可使用可靠的州和城市。
    cleaned["can_group_by_city_state"] = ~cleaned[
        ["flag_state_format_invalid", "flag_state_unknown", "flag_city_missing"]
    ].any(axis=1)
    return cleaned


def check_customer_locations(raw, cleaned):
    """检查原始缺失、空白和规范变化；只有空格的值与真正缺失分别统计。"""
    checks = {}
    for col in LOCATION_COLS:
        checks[col] = {
            "原始缺失数": int(raw[col].isna().sum()),
            "非空但只有空白字符数": int((raw[col].notna() & raw[col].str.strip().eq("")).sum()),
            "规范后变化记录数": int((raw[col].notna() & raw[col].ne(cleaned[col])).sum()),
        }
    return pd.DataFrame(checks).T


def customer_field_changes(raw, cleaned):
    """仅输出真正发生变化的字段，便于追溯，不向工作表堆叠原值列。"""
    changes = []
    for col in LOCATION_COLS:
        changed = raw[col].notna() & raw[col].ne(cleaned[col])
        if changed.any():
            changes.append(pd.DataFrame({
                "customer_id": raw.loc[changed, "customer_id"],
                "字段": col,
                "原始值": raw.loc[changed, col],
                "规范值": cleaned.loc[changed, col],
            }))
    return pd.concat(changes, ignore_index=True) if changes else pd.DataFrame(
        columns=["customer_id", "字段", "原始值", "规范值"])


def join_orders_customers(raw_orders, cleaned):
    """在当前数据的一对一关系下左连接，保留每个订单及对应客户记录。"""
    _require_columns(raw_orders, ["order_id", "customer_id", "order_status"], "订单原表")
    _check_primary_key(raw_orders, "order_id", "订单原表")
    _check_nonblank(raw_orders, "customer_id", "订单原表")
    _check_primary_key(cleaned, "customer_id", "客户工作表")
    if not raw_orders["order_status"].isin(ORDER_STATUSES).all():
        raise ValueError("订单状态缺失或未知")
    if set(cleaned.columns) & (set(raw_orders.columns) - {"customer_id"}):
        raise ValueError("订单输入已包含客户字段，请使用订单原表")
    if (~raw_orders["customer_id"].isin(cleaned["customer_id"])).any():
        raise ValueError("订单存在无法匹配客户表的 customer_id，请先核查")

    # 当前原始文件中订单侧 customer_id 也唯一，因此延续课堂的一对一校验。
    # customer_unique_id 可以重复；它不是本次连接用的键。
    joined = raw_orders.copy().merge(
        cleaned, on="customer_id", how="left", validate="one_to_one",
        indicator="customers_match")
    joined["flag_missing_customer"] = joined["customers_match"].eq("left_only")
    return joined


def summarize_city_orders(joined):
    """每行一个州+城市组合；订单数基于一行一个订单的关联表。"""
    _require_columns(joined, [
        "order_id", "customer_state", "customer_city", "can_group_by_city_state",
    ], "订单客户关联表")
    _check_primary_key(joined, "order_id", "订单客户关联表")
    # 只在筛选表达式中把未知排除；原表保留，无法分组订单数量另报。
    eligible = joined.loc[joined["can_group_by_city_state"].fillna(False)]
    return eligible.groupby(["customer_state", "customer_city"], as_index=False).agg(
        order_count=("order_id", "size")
    ).sort_values(["order_count", "customer_state", "customer_city"], ascending=[False, True, True]).reset_index(drop=True)


def summarize_customer_identity(cleaned):
    """一行一个跨订单客户标识，仅作映射观察，不直接给出复购标签。"""
    stats = cleaned.groupby("customer_unique_id").agg(
        customer_record_count=("customer_id", "size"),
        postcode_count=("customer_zip_code_prefix", "nunique"),
        state_count=("customer_state", "nunique"),
    )
    # 仅为计算不同地区组合建立观察视图，客户明细仍全部保留。
    city_pairs = cleaned[["customer_unique_id", "customer_state", "customer_city"]].drop_duplicates()
    city_count = city_pairs.groupby("customer_unique_id").size()
    stats["city_state_count"] = city_count
    return stats.reset_index()


def reconcile_customer_totals(raw_orders, cleaned, joined, city_orders):
    # raw_orders：原始订单表
    # cleaned：清洗后的客户维表（客户基础信息表）
    # joined：订单和客户维表join之后的结果表
    # city_orders：按城市+地区聚合后的订单汇总表
    """核对关联和地区聚合，允许客户维表中存在当前没有订单的记录。"""
    # 匹配客户数要取“本批订单用到的客户记录”，不能假定维表记录全部被使用。
    expected_customers = cleaned.loc[cleaned["customer_id"].isin(raw_orders["customer_id"])]
    eligible_orders = int(joined["can_group_by_city_state"].fillna(False).sum())
    checks = pd.DataFrame({
        "来源或预期": [
            len(raw_orders), raw_orders["order_id"].nunique(),
            int(raw_orders["customer_id"].isin(cleaned["customer_id"]).sum()),
            expected_customers["customer_unique_id"].nunique(), eligible_orders,
        ],
        "处理后": [
            len(joined), joined["order_id"].nunique(),
            int(joined["customers_match"].eq("both").sum()),
            joined["customer_unique_id"].nunique(), int(city_orders["order_count"].sum()),
        ],
    }, index=["订单行数", "订单ID不同值数", "匹配客户订单数", "匹配的客户标识数", "可按州城市分组的订单数"])
    checks["差额"] = checks["处理后"] - checks["来源或预期"]
    if checks["差额"].ne(0).any():
        raise ValueError("客户关联或地区聚合数量核对不一致")
    return checks


def summarize_customer_metrics(raw, cleaned, joined, city_orders, identities):
    city_states = cleaned.groupby("customer_city")["customer_state"].nunique()
    return {
        "customer_rows": int(len(cleaned)),
        "customer_id_unique": int(cleaned["customer_id"].nunique()),
        "customer_unique_id_unique": int(cleaned["customer_unique_id"].nunique()),
        "customer_unique_id_duplicate_rows": int(cleaned.duplicated(["customer_unique_id"]).sum()),
        "unique_ids_with_multiple_records": int(identities["customer_record_count"].gt(1).sum()),
        "max_records_per_unique_id": int(identities["customer_record_count"].max()),
        "unique_ids_with_multiple_postcodes": int(identities["postcode_count"].gt(1).sum()),
        "unique_ids_with_multiple_city_states": int(identities["city_state_count"].gt(1).sum()),
        "unique_ids_with_multiple_states": int(identities["state_count"].gt(1).sum()),
        "zip_format_invalid_rows": int(cleaned["flag_zip_format_invalid"].sum()),
        "state_format_invalid_rows": int(cleaned["flag_state_format_invalid"].sum()),
        "state_unknown_rows": int(cleaned["flag_state_unknown"].sum()),
        "city_missing_rows": int(cleaned["flag_city_missing"].sum()),
        "location_review_rows": int(cleaned["flag_customer_location_needs_review"].sum()),
        "leading_zero_zip_rows": int(cleaned["customer_zip_code_prefix"].str.startswith("0").sum()),
        "distinct_state_labels": int(cleaned["customer_state"].nunique()),
        "distinct_city_labels": int(cleaned["customer_city"].nunique()),
        "city_names_across_multiple_states": int(city_states.gt(1).sum()),
        "all_order_rows": int(len(joined)),
        "orders_missing_customer": int(joined["flag_missing_customer"].sum()),
        "customer_records_without_order": int((~cleaned["customer_id"].isin(joined["customer_id"])).sum()),
        "city_state_order_groups": int(len(city_orders)),
        "orders_in_city_state_groups": int(city_orders["order_count"].sum()),
        "orders_excluded_from_city_state_groups": int((~joined["can_group_by_city_state"].fillna(False)).sum()),
        "normalization_changes": {
            col: int((raw[col].notna() & raw[col].ne(cleaned[col])).sum()) for col in LOCATION_COLS
        },
    }
