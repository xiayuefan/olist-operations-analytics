"""商品明细课堂流程 v1：精确金额、订单汇总、关联与核对。

不删除原始记录，不填补缺少明细的订单金额。兼容 Python 3.7+ / Pandas 1.1+。
"""

from decimal import Decimal, InvalidOperation

import pandas as pd

from orders_cleaning import ORDER_STATUSES


ITEM_KEY_COLS = ["order_id", "order_item_id"]
SUMMARY_COLS = [
    "item_line_count", "product_count", "seller_count",
    "goods_amount_cents", "freight_amount_cents",
]
MONEY_COLS = ["goods_amount_cents", "freight_amount_cents"]
PROGRESSED_STATUSES = ["approved", "invoiced", "processing", "shipped", "delivered"]


def to_cents(raw_value):
    """从原始字符串精确换算整数分；有限且不含不足一分的部分。"""
    if not isinstance(raw_value, str):
        raise ValueError("金额转换需要原始字符串，请从原始 CSV 读取")
    try:
        amount = Decimal(raw_value)
    except InvalidOperation as exc:
        raise ValueError("金额无法解析，请核查原始值") from exc
    if not amount.is_finite():
        raise ValueError("金额必须是有限数值")
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise ValueError("金额无法精确转换为整数分，需要核查")
    return int(cents)


def clean_order_items(raw_items):
    """返回工作副本：规范类型、精确换算金额并保留业务标记。"""
    required = set(ITEM_KEY_COLS + [
        "product_id", "seller_id", "shipping_limit_date", "price", "freight_value",
    ])
    missing = sorted(required - set(raw_items.columns))
    if missing:
        raise ValueError("商品明细缺少列：" + ", ".join(missing))
    if raw_items.empty:
        raise ValueError("商品明细表为空，请检查输入")
    cleaned = raw_items.copy()

    for col in ITEM_KEY_COLS + ["product_id", "seller_id"]:
        if cleaned[col].isna().any() or cleaned[col].astype(str).str.strip().eq("").any():
            raise ValueError("{} 存在缺失或空白，请先核查".format(col))
    if cleaned.duplicated(ITEM_KEY_COLS).any():
        raise ValueError("商品明细组合键重复，请先核查；不自动去重")

    # 额外类型规范：明细序号为正整数，转换后再次确认组合唯一性。
    item_numbers = pd.to_numeric(cleaned["order_item_id"], errors="coerce")
    if (item_numbers.isna().any()
            or item_numbers.isin([float("inf"), float("-inf")]).any()
            or item_numbers.le(0).any()
            or item_numbers.mod(1).ne(0).any()):
        raise ValueError("order_item_id 应为正整数，请先核查")
    cleaned["order_item_id"] = item_numbers.astype("Int64")
    if cleaned.duplicated(ITEM_KEY_COLS).any():
        raise ValueError("明细序号转换后组合键重复，请核查不同字符串是否表示同一序号")

    for source_col, cents_col in [("price", "price_cents"), ("freight_value", "freight_cents")]:
        # 精确金额始终从原始字符串换算，不先经过 float。
        cleaned[cents_col] = raw_items[source_col].map(to_cents)
        if cleaned[cents_col].lt(0).any():
            raise ValueError("{} 存在负数，请核查后再汇总".format(source_col))
        cleaned[source_col] = pd.to_numeric(raw_items[source_col], errors="raise")

    shipping = pd.to_datetime(
        raw_items["shipping_limit_date"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    if (raw_items["shipping_limit_date"].notna() & shipping.isna()).any():
        raise ValueError("发货截止时间存在非空但无法解析的值，请核查")
    cleaned["shipping_limit_date"] = shipping
    cleaned["flag_missing_shipping_limit_date"] = shipping.isna()
    cleaned["flag_zero_price"] = cleaned["price_cents"].eq(0)
    cleaned["is_zero_freight"] = cleaned["freight_cents"].eq(0)
    return cleaned


def check_reference(detail_key, reference_key):
    """复用课堂逻辑，只统计键问题，不修改输入。"""
    return {
        "维表主键缺失数": int(reference_key.isna().sum()),
        "维表主键重复数": int(reference_key.duplicated().sum()),
        "明细外键缺失数": int(detail_key.isna().sum()),
        "非空但未匹配明细数": int((detail_key.notna() & ~detail_key.isin(reference_key)).sum()),
    }


def check_item_references(cleaned, product_keys, seller_keys):
    return pd.DataFrame({
        "商品关联": check_reference(cleaned["product_id"], product_keys),
        "卖家关联": check_reference(cleaned["seller_id"], seller_keys),
    })


def aggregate_order_items(cleaned):
    """由明细粒度汇总为订单粒度；未知金额不能通过 sum 被悄悄跳过。"""
    if cleaned.empty:
        raise ValueError("商品明细为空，无法汇总")
    if cleaned[ITEM_KEY_COLS + ["price_cents", "freight_cents"]].isna().any().any():
        raise ValueError("主键或金额缺失，请先核查再汇总")
    if cleaned.duplicated(ITEM_KEY_COLS).any():
        raise ValueError("组合键重复，请先核查再汇总")
    return cleaned.groupby("order_id", as_index=False).agg(
        item_line_count=("order_item_id", "size"),
        product_count=("product_id", "nunique"),
        seller_count=("seller_id", "nunique"),
        goods_amount_cents=("price_cents", "sum"),
        freight_amount_cents=("freight_cents", "sum"),
    )


def join_orders_items(raw_orders, summary):
    """订单主表左关联汇总，验证两侧主键、外键覆盖和关联后金额。"""
    orders_base = raw_orders[["order_id", "order_status"]].copy()
    for name, frame in [("订单表", orders_base), ("商品汇总表", summary)]:
        if frame["order_id"].isna().any() or frame["order_id"].astype(str).str.strip().eq("").any():
            raise ValueError(name + "存在空订单 ID")
        if frame["order_id"].duplicated().any():
            raise ValueError(name + "订单 ID 不唯一")
    if not orders_base["order_status"].isin(ORDER_STATUSES).all():
        raise ValueError("订单状态缺失或未知，请核查")
    if summary[SUMMARY_COLS].isna().any().any():
        raise ValueError("商品汇总值缺失，请核查")
    if (~summary["order_id"].isin(orders_base["order_id"])).any():
        raise ValueError("商品汇总中存在找不到订单主表的订单，请核查")

    joined = orders_base.merge(
        summary, on="order_id", how="left", validate="one_to_one", indicator="items_match")
    for col in SUMMARY_COLS:
        joined[col] = joined[col].astype("Int64")
    joined["flag_missing_items"] = joined["items_match"].eq("left_only")
    joined["flag_progressed_missing_items"] = (
        joined["flag_missing_items"] & joined["order_status"].isin(PROGRESSED_STATUSES))
    for col in MONEY_COLS:
        if int(summary[col].sum()) != int(joined[col].sum()):
            raise ValueError("关联后 {} 总额变化，请核查".format(col))
    return joined


def reconcile_item_totals(cleaned, summary, joined):
    """明细、订单汇总、关联后三个层次的控制总额。"""
    checks = pd.DataFrame({
        "明细层": [len(cleaned), cleaned["price_cents"].sum(), cleaned["freight_cents"].sum()],
        "订单汇总层": [summary["item_line_count"].sum(), summary["goods_amount_cents"].sum(), summary["freight_amount_cents"].sum()],
        "关联后": [joined["item_line_count"].sum(), joined["goods_amount_cents"].sum(), joined["freight_amount_cents"].sum()],
    }, index=["商品明细数量", "商品金额（分）", "运费（分）"])
    checks["汇总差额"] = checks["订单汇总层"] - checks["明细层"]
    checks["关联差额"] = checks["关联后"] - checks["订单汇总层"]
    if checks[["汇总差额", "关联差额"]].ne(0).any().any():
        raise ValueError("明细数量或金额核对不一致，请检查")
    return checks


def summarize_item_metrics(cleaned, summary, joined):
    """已交付商品成交额不含运费；计数和金额保持整数，客单价用于展示。"""
    delivered = joined.loc[joined["order_status"].eq("delivered")]
    if delivered[MONEY_COLS].isna().any().any():
        raise ValueError("已交付订单缺少商品金额或运费，请先核查")
    count = len(delivered)
    goods_cents = int(delivered["goods_amount_cents"].sum()) if count else None
    freight_cents = int(delivered["freight_amount_cents"].sum()) if count else None
    return {
        "item_rows": int(len(cleaned)),
        "orders_with_items": int(len(summary)),
        "all_order_rows": int(len(joined)),
        "orders_missing_items": int(joined["flag_missing_items"].sum()),
        "priority_missing_items": int(joined["flag_progressed_missing_items"].sum()),
        "zero_freight_item_rows": int(cleaned["is_zero_freight"].sum()),
        "zero_freight_orders": int(summary["freight_amount_cents"].eq(0).sum()),
        "zero_price_item_rows": int(cleaned["flag_zero_price"].sum()),
        "missing_shipping_limit_rows": int(cleaned["flag_missing_shipping_limit_date"].sum()),
        "all_goods_cents": int(cleaned["price_cents"].sum()),
        "all_freight_cents": int(cleaned["freight_cents"].sum()),
        "delivered_orders": int(count),
        "delivered_goods_cents": goods_cents,
        "delivered_freight_cents": freight_cents,
        "delivered_goods_aov_brl": goods_cents / count / 100 if count else None,
    }
