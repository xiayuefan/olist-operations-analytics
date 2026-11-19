"""订单表课堂整理：按 v1（六条）或 v2（八条）规则增加核查标记。

输入为原始订单 DataFrame，输出为工作副本。
兼容 Python 3.7+ / Pandas 1.1+；不需要新增第三方依赖。
默认 v1，保留原课堂调用方式。版本差异见 docs/03_订单规则更新.md。
"""

import pandas as pd


TIME_COLS = [
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
]

REVIEW_FLAG_COLS = [
    "flag_delivered_missing_date",
    "flag_delivered_missing_approval",
    "flag_delivered_missing_carrier",
    "flag_carrier_before_purchase",
    "flag_delivery_before_carrier",
    "flag_canceled_has_delivery_date",
]

ADDITIONAL_REVIEW_FLAG_COLS = [
    "flag_approval_before_purchase",
    "flag_carrier_before_approval",
]

ORDER_STATUSES = {
    "created", "approved", "invoiced", "processing",
    "shipped", "delivered", "canceled", "unavailable",
}


def get_review_flag_cols(rules_version="v1"):
    """返回指定版本的标记列表，不修改默认六条规则。"""
    if rules_version == "v1":
        return REVIEW_FLAG_COLS.copy()
    if rules_version == "v2":
        return REVIEW_FLAG_COLS + ADDITIONAL_REVIEW_FLAG_COLS
    raise ValueError("rules_version 只支持 v1 或 v2")


def add_time_order_flag(df, earlier_col, later_col, flag_name):
    """课堂函数：两个字段已转为时间类型，且均有值时才比较先后。"""
    result = df.copy()
    can_compare = result[earlier_col].notna() & result[later_col].notna()
    result[flag_name] = can_compare & result[later_col].lt(result[earlier_col])
    return result


def clean_orders(raw_orders, rules_version="v1"):
    """返回带时间类型、指定版本核查标记及两个指标的副本，原表不变。

    必需列缺失、订单主键异常、未知状态或非空日期解析失败时停止，
    避免未经核查的数据继续生成结果；已知缺失和冲突保留并标记。
    """
    flag_cols = get_review_flag_cols(rules_version)
    required = {"order_id", "customer_id", "order_status"}.union(TIME_COLS)
    missing_cols = sorted(required - set(raw_orders.columns))
    if missing_cols:
        raise ValueError("缺少必需列：" + ", ".join(missing_cols))
    if raw_orders.empty:
        raise ValueError("订单表为空，请检查输入文件")

    cleaned = raw_orders.copy()
    order_ids = cleaned["order_id"]
    if order_ids.isna().any() or order_ids.astype(str).str.strip().eq("").any():
        raise ValueError("订单 ID 存在缺失或空白，请先核查")
    if order_ids.duplicated().any():
        raise ValueError("订单 ID 不唯一，请核查重复记录；本函数不自动去重")
    if not cleaned["order_status"].isin(ORDER_STATUSES).all():
        raise ValueError("订单状态存在缺失或不在约定的八种状态中，请先核查")

    for col in TIME_COLS:
        original = cleaned[col]
        parsed = pd.to_datetime(original, format="%Y-%m-%d %H:%M:%S", errors="coerce")
        failed = original.notna() & parsed.isna()
        if failed.any():
            raise ValueError("{} 有 {} 条非空日期无法解析，请先核查".format(col, int(failed.sum())))
        cleaned[col] = parsed

    purchase = cleaned["order_purchase_timestamp"]
    approved = cleaned["order_approved_at"]
    carrier = cleaned["order_delivered_carrier_date"]
    delivery = cleaned["order_delivered_customer_date"]
    estimated = cleaned["order_estimated_delivery_date"]
    is_delivered = cleaned["order_status"].eq("delivered")
    can_check_carrier = purchase.notna() & carrier.notna()
    can_check_delivery = carrier.notna() & delivery.notna()

    # 六条规则与课堂版本完全一致；不把正常的未交付时间缺失统一视为错误。
    cleaned["flag_delivered_missing_date"] = is_delivered & delivery.isna()
    cleaned["flag_delivered_missing_approval"] = is_delivered & approved.isna()
    cleaned["flag_delivered_missing_carrier"] = is_delivered & carrier.isna()
    cleaned["flag_carrier_before_purchase"] = can_check_carrier & carrier.lt(purchase)
    cleaned["flag_delivery_before_carrier"] = can_check_delivery & delivery.lt(carrier)
    cleaned["flag_canceled_has_delivery_date"] = cleaned["order_status"].eq("canceled") & delivery.notna()
    if rules_version == "v2":
        cleaned = add_time_order_flag(
            cleaned, "order_purchase_timestamp", "order_approved_at", "flag_approval_before_purchase")
        cleaned = add_time_order_flag(
            cleaned, "order_approved_at", "order_delivered_carrier_date", "flag_carrier_before_approval")
    cleaned["review_rule_count"] = cleaned[flag_cols].sum(axis=1)
    cleaned["flag_needs_review"] = cleaned[flag_cols].any(axis=1)

    # 运输天数为实际经过秒数 / 86400，保留小数；未满足条件的指标保持缺失。
    cleaned["transit_days_raw"] = (delivery - carrier).dt.total_seconds() / 86400
    cleaned["is_valid_transit"] = (
        is_delivered & can_check_carrier & can_check_delivery
        & ~cleaned["flag_carrier_before_purchase"]
        & ~cleaned["flag_delivery_before_carrier"]
    )
    cleaned["transit_days"] = cleaned["transit_days_raw"].where(cleaned["is_valid_transit"])

    # 延迟按自然日判断；当天送达不因时分秒被误判为晚于预计日期。
    actual_day = delivery.dt.normalize()
    estimated_day = estimated.dt.normalize()
    purchase_day = purchase.dt.normalize()
    cleaned["is_valid_delay"] = (
        is_delivered & actual_day.notna() & estimated_day.notna()
        & delivery.ge(purchase) & estimated_day.ge(purchase_day)
    )
    cleaned["delivery_delay_days"] = (
        (actual_day - estimated_day).dt.days.where(cleaned["is_valid_delay"])
    )
    return cleaned


def summarize_metrics(cleaned, rules_version="v1"):
    """按生成数据时的同一版本汇总；无有效样本时指标为 None。"""
    flag_cols = get_review_flag_cols(rules_version)
    expected_review = cleaned[flag_cols].any(axis=1)
    expected_hits = cleaned[flag_cols].sum(axis=1)
    if (not expected_review.equals(cleaned["flag_needs_review"])
            or not expected_hits.equals(cleaned["review_rule_count"])):
        raise ValueError("数据的核查标记与汇总规则版本不一致，请使用同一版本重新生成和汇总")
    transit = cleaned.loc[cleaned["is_valid_transit"], "transit_days"]
    delay = cleaned.loc[cleaned["is_valid_delay"], "delivery_delay_days"]
    return {
        "order_rows": int(len(cleaned)),
        "review_rule_hits": int(cleaned[flag_cols].sum().sum()),
        "review_orders": int(cleaned["flag_needs_review"].sum()),
        "delivered_orders": int(cleaned["order_status"].eq("delivered").sum()),
        "valid_transit_orders": int(len(transit)),
        "transit_mean_days": float(transit.mean()) if len(transit) else None,
        "transit_p50_days": float(transit.quantile(0.5)) if len(transit) else None,
        "transit_p90_days": float(transit.quantile(0.9)) if len(transit) else None,
        "transit_p95_days": float(transit.quantile(0.95)) if len(transit) else None,
        "transit_p99_days": float(transit.quantile(0.99)) if len(transit) else None,
        "transit_max_days": float(transit.max()) if len(transit) else None,
        "valid_delay_orders": int(len(delay)),
        "late_orders": int(delay.gt(0).sum()),
        "late_rate": float(delay.gt(0).mean()) if len(delay) else None,
    }


def summarize_rule_coverage(cleaned, rules_version="v1"):
    """报告各规则适用范围；不把缺少比较时间的记录默认为正常。"""
    delivered = cleaned["order_status"].eq("delivered")
    scopes = {
        "flag_delivered_missing_date": (delivered, "状态为已交付"),
        "flag_delivered_missing_approval": (delivered, "状态为已交付"),
        "flag_delivered_missing_carrier": (delivered, "状态为已交付"),
        "flag_carrier_before_purchase": (
            cleaned["order_purchase_timestamp"].notna()
            & cleaned["order_delivered_carrier_date"].notna(), "下单与交物流时间均有值"),
        "flag_delivery_before_carrier": (
            cleaned["order_delivered_carrier_date"].notna()
            & cleaned["order_delivered_customer_date"].notna(), "交物流与送达时间均有值"),
        "flag_canceled_has_delivery_date": (
            cleaned["order_status"].eq("canceled"), "状态为取消"),
        "flag_approval_before_purchase": (
            cleaned["order_purchase_timestamp"].notna()
            & cleaned["order_approved_at"].notna(), "下单与审批时间均有值"),
        "flag_carrier_before_approval": (
            cleaned["order_approved_at"].notna()
            & cleaned["order_delivered_carrier_date"].notna(), "审批与交物流时间均有值"),
    }
    rows = []
    for flag in get_review_flag_cols(rules_version):
        eligible, description = scopes[flag]
        rows.append({
            "rule": flag, "scope": description,
            "eligible_orders": int(eligible.sum()),
            "outside_scope_orders": int((~eligible).sum()),
            "flagged_orders": int(cleaned[flag].sum()),
        })
    return pd.DataFrame(rows)
