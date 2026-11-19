"""卖家属性、销售汇总和订单卖家关系。"""

import pandas as pd

from customers_cleaning import STATE_CODES
from items_cleaning import ITEM_KEY_COLS


LOCATION_COLS = ["seller_zip_code_prefix", "seller_city", "seller_state"]
LOCATION_FLAGS = [
    "flag_zip_format_invalid", "flag_state_format_invalid",
    "flag_state_unknown", "flag_city_missing",
]
ORDER_SELLER_KEY = ["order_id", "seller_id"]


def _check_seller_key(sellers):
    seller_ids = sellers["seller_id"]
    if (
        seller_ids.empty or seller_ids.isna().any()
        or seller_ids.astype(str).str.strip().eq("").any()
        or seller_ids.duplicated().any()
    ):
        raise ValueError("卖家 ID 必须非空且唯一")


def clean_sellers(raw):
    """返回一行一个卖家的属性副本，规范地区并附上质量标记。"""
    missing = set(["seller_id"] + LOCATION_COLS) - set(raw.columns)
    if missing:
        raise ValueError("卖家原表缺少列：" + ", ".join(sorted(missing)))
    _check_seller_key(raw)
    sellers = raw.copy()
    for col in LOCATION_COLS:
        # 邮编以原始文本读取，前导零是邮编的一部分。
        if not raw[col].dropna().map(lambda value: isinstance(value, str)).all():
            raise ValueError("请按字符串读取地区字段：" + col)
        sellers[col] = raw[col].astype("string").str.strip()
    sellers["seller_city"] = sellers["seller_city"].str.lower()
    sellers["seller_state"] = sellers["seller_state"].str.upper()

    # 格式检查与州代码取值检查分别记录。
    zip_prefix = sellers["seller_zip_code_prefix"]
    state = sellers["seller_state"]
    sellers["flag_zip_format_invalid"] = ~zip_prefix.str.fullmatch("[0-9]{5}", na=False)
    sellers["flag_state_format_invalid"] = ~state.str.fullmatch("[A-Z]{2}", na=False)
    sellers["flag_state_unknown"] = ~state.isin(STATE_CODES)
    sellers["flag_city_missing"] = sellers["seller_city"].fillna("").eq("")
    return sellers


def join_items_sellers(items, sellers):
    """用卖家 ID 给已规范的商品明细补充属性。"""
    _check_seller_key(sellers)
    if not items["seller_id"].isin(sellers["seller_id"]).all():
        raise ValueError("存在无法关联卖家的商品明细")

    # 左侧可以有同一卖家的多条明细，右侧每个卖家只有一条属性记录。
    joined = items.merge(
        sellers, on="seller_id", how="left", validate="many_to_one",
        indicator="sellers_match",
    )
    if joined.duplicated(ITEM_KEY_COLS).any():
        raise ValueError("关联后的商品明细组合主键重复")
    if not joined[items.columns].equals(items.reset_index(drop=True)):
        raise ValueError("关联后的来源明细字段与输入不一致")
    return joined


def summarize_seller_sales(items_with_sellers, sellers):
    """从商品明细生成一行一个有明细的卖家的销售汇总。"""
    # size 统计行数，nunique 在各卖家的分组内统计不同值数。
    summary = items_with_sellers.groupby("seller_id", as_index=False).agg(
        item_line_count=("order_item_id", "size"),
        order_count=("order_id", "nunique"),
        product_count=("product_id", "nunique"),
        goods_amount_cents=("price_cents", "sum"),
        freight_amount_cents=("freight_cents", "sum"),
    )
    profile = summary.merge(
        sellers, on="seller_id", how="left", validate="one_to_one",
        indicator="seller_attributes_match",
    )
    if not profile["seller_attributes_match"].eq("both").all():
        raise ValueError("存在无法关联卖家属性的销售汇总")
    return profile


def build_order_seller_pairs(items):
    """返回一行一个订单与卖家组合，附该组合的明细行数。"""
    return items.groupby(ORDER_SELLER_KEY, as_index=False).agg(
        item_line_count=("order_item_id", "size"),
    )


def reconcile_seller_totals(items, profile, pairs):
    """核对可相加的明细、金额，以及订单卖家关系的计数。"""
    # 卖家订单数的合计对应关系表行数，全局订单数对应不同 order_id。
    controls = pd.DataFrame({
        "应有值": [
            len(items), int(items["price_cents"].sum()), int(items["freight_cents"].sum()),
            len(pairs), len(items), items["order_id"].nunique(),
        ],
        "实际值": [
            int(profile["item_line_count"].sum()),
            int(profile["goods_amount_cents"].sum()),
            int(profile["freight_amount_cents"].sum()),
            int(profile["order_count"].sum()),
            int(pairs["item_line_count"].sum()), pairs["order_id"].nunique(),
        ],
    }, index=[
        "卖家汇总明细数", "卖家汇总商品金额（分）", "卖家汇总运费（分）",
        "各卖家订单数之和", "关系表明细数", "关系表不同订单数",
    ])
    controls["差额"] = controls["实际值"] - controls["应有值"]
    if controls["差额"].ne(0).any():
        raise ValueError("卖家汇总或订单卖家关系计数与来源不一致")
    return controls
