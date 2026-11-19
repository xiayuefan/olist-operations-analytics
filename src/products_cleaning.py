"""商品与品类翻译阶段 v1：保留商品、按指标计算特征、增强销售明细。

商品表一行一个 product_id；销售明细的主键是 order_id + order_item_id。
兼容 Python 3.7+ / Pandas 1.1+，不自动翻译、不填零、不删除缺少属性的商品。
"""

import pandas as pd
from pandas.api.types import is_integer_dtype

from items_cleaning import ITEM_KEY_COLS


NUMERIC_COLS = [
    "product_name_lenght", "product_description_lenght", "product_photos_qty",
    "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm",
]
DIMENSION_COLS = ["product_length_cm", "product_height_cm", "product_width_cm"]
CONTENT_COLS = ["product_name_lenght", "product_description_lenght", "product_photos_qty"]
MONEY_COLS = ["price_cents", "freight_cents"]
BLOCKING_CHECKS = ["非空但解析失败数", "非有限数", "非整数数", "负数数"]


def _require_columns(frame, cols, label):
    missing = sorted(set(cols) - set(frame.columns))
    if missing:
        raise ValueError(label + "缺少列：" + ", ".join(missing))
    if frame.empty:
        raise ValueError(label + "为空，请核查输入")


def _check_nonblank(frame, col, label):
    if frame[col].isna().any() or frame[col].astype(str).str.strip().eq("").any():
        raise ValueError(label + "存在缺失或空白：" + col)


def _check_key(frame, cols, label):
    _require_columns(frame, cols, label)
    for col in cols:
        _check_nonblank(frame, col, label)
    if frame.duplicated(cols).any():
        raise ValueError(label + "主键重复，请核查；不自动去重")


def join_product_categories(raw_products, raw_translation):
    """商品左连接品类映射，保留原始品类及两类英文名称缺失标记。"""
    _require_columns(raw_products, ["product_id", "product_category_name"] + NUMERIC_COLS, "商品原表")
    _check_key(raw_products, ["product_id"], "商品原表")
    _require_columns(raw_translation, [
        "product_category_name", "product_category_name_english",
    ], "翻译原表")
    _check_key(raw_translation, ["product_category_name"], "翻译原表")
    _check_nonblank(raw_translation, "product_category_name_english", "翻译原表")
    if {"product_category_name_english", "category_match"} & set(raw_products.columns):
        raise ValueError("商品输入已包含翻译字段，请使用商品原表")

    # 同一原始品类可对应多个商品；右侧品类键必须唯一。
    # 英文名称列不要求唯一，不同原始品类可以共用英文展示名称。
    joined = raw_products.copy().merge(
        raw_translation[["product_category_name", "product_category_name_english"]],
        on="product_category_name", how="left", validate="many_to_one", indicator="category_match")
    category = joined["product_category_name"]
    joined["flag_category_missing"] = category.isna() | category.str.strip().eq("")
    joined["flag_category_untranslated"] = (
        ~joined["flag_category_missing"] & joined["category_match"].eq("left_only"))
    # 不把缺失译名擅自归入某个品类；本阶段保留原始值和缺失原因。
    return joined


def check_product_numeric(products):
    """检查用临时数值表，不覆盖输入；原始缺失与非空解析失败分别统计。"""
    _require_columns(products, NUMERIC_COLS, "商品属性表")
    numbers = products[NUMERIC_COLS].apply(pd.to_numeric, errors="coerce")
    return pd.DataFrame({
        "原始缺失数": products[NUMERIC_COLS].isna().sum(),
        "非空但解析失败数": (products[NUMERIC_COLS].notna() & numbers.isna()).sum(),
        "非有限数": numbers.isin([float("inf"), float("-inf")]).sum(),
        "非整数数": (numbers.notna() & numbers.mod(1).ne(0)).sum(),
        "负数数": numbers.lt(0).sum(),
        "零值数": numbers.eq(0).sum(),
    })


def clean_product_attributes(products_with_categories):
    """返回完整商品工作副本，原始缺失保持未知，体积和重量各用各的条件。"""
    _require_columns(products_with_categories, ["product_id"] + NUMERIC_COLS, "商品属性表")
    _check_key(products_with_categories, ["product_id"], "商品属性表")
    checks = check_product_numeric(products_with_categories)
    if checks[BLOCKING_CHECKS].ne(0).any().any():
        raise ValueError("商品数值存在解析失败、非有限数、非整数或负数，请先核查")

    cleaned = products_with_categories.copy()
    # 本批原始数值的非空记录精度均为整数，采用 Int64 保留缺失。
    # 这不表示所有业务场景的厘米、克数都必须为整数；不对小数进行舍入猜测。
    cleaned[NUMERIC_COLS] = products_with_categories[NUMERIC_COLS].apply(
        pd.to_numeric, errors="raise").astype("Int64")
    cleaned["flag_weight_missing"] = cleaned["product_weight_g"].isna()
    # 缺少重量时 eq(0) 保持 <NA>，不把未知误标成“已知不是零”。
    cleaned["flag_weight_zero"] = cleaned["product_weight_g"].eq(0)
    cleaned["can_use_weight"] = (
        cleaned["product_weight_g"].notna() & cleaned["product_weight_g"].gt(0))
    cleaned["flag_content_metadata_missing"] = cleaned[CONTENT_COLS].isna().any(axis=1)
    cleaned["flag_dimensions_missing"] = cleaned[DIMENSION_COLS].isna().any(axis=1)
    cleaned["flag_dimensions_nonpositive"] = cleaned[DIMENSION_COLS].le(0).any(axis=1)

    # 体积只依赖三边：重量为零、缺少品类或图片数量，不会自动取消体积资格。
    cleaned["can_calculate_volume"] = (
        cleaned[DIMENSION_COLS].notna().all(axis=1)
        & cleaned[DIMENSION_COLS].gt(0).all(axis=1))
    cleaned["product_volume_cm3"] = (
        cleaned["product_length_cm"] * cleaned["product_height_cm"] * cleaned["product_width_cm"]
    ).where(cleaned["can_calculate_volume"])
    # 当前构造的是记录尺寸的长宽高乘积；不可计算时保持 <NA>，不填成零。
    return cleaned


def join_items_products(items_clean, products_clean):
    """将商品属性带入销售明细，输出仍是一行一条订单商品明细。"""
    _require_columns(items_clean, ITEM_KEY_COLS + ["product_id"] + MONEY_COLS, "销售明细")
    _check_key(items_clean, ITEM_KEY_COLS, "销售明细")
    _check_nonblank(items_clean, "product_id", "销售明细")
    _check_key(products_clean, ["product_id"], "商品工作表")
    for col in MONEY_COLS:
        if items_clean[col].isna().any() or not is_integer_dtype(items_clean[col].dtype):
            raise ValueError("明细金额须为非空整数分，请复用商品明细清洗函数：" + col)
        if items_clean[col].lt(0).any():
            raise ValueError("明细金额存在负数，请核查")
    if (set(items_clean.columns) & set(products_clean.columns)) - {"product_id"}:
        raise ValueError("输入存在商品 ID 以外的同名字段，请使用独立的明细和商品表")
    if (~items_clean["product_id"].isin(products_clean["product_id"])).any():
        raise ValueError("明细存在找不到商品表的 product_id，须先核查再输出")

    # 左侧同一商品可以被多次购买，不能要求左侧 product_id 唯一。
    # 右侧商品主键唯一，防止一条销售明细匹配多个属性记录而放大金额。
    return items_clean.copy().merge(
        products_clean, on="product_id", how="left",
        validate="many_to_one", indicator="products_match")


def reconcile_product_totals(items_clean, joined):
    """按整数分核对数量、商品金额及运费；商品属性不应改变销售事实。"""
    checks = pd.DataFrame({
        "关联前": [len(items_clean), int(items_clean["price_cents"].sum()), int(items_clean["freight_cents"].sum())],
        "关联后": [len(joined), int(joined["price_cents"].sum()), int(joined["freight_cents"].sum())],
    }, index=["商品明细行数", "商品金额（分）", "运费（分）"])
    checks["差额"] = checks["关联后"] - checks["关联前"]
    if checks["差额"].ne(0).any() or joined.duplicated(ITEM_KEY_COLS).any():
        raise ValueError("商品属性关联后数量、金额或明细主键异常，请核查")
    return checks


def product_attribute_coverage(products, joined):
    """同一质量条件分别按商品和销售明细计数，避免混淆粒度。"""
    return pd.DataFrame({
        "商品数": [
            int(products["flag_category_missing"].sum()),
            int(products["flag_category_untranslated"].sum()),
            int((~products["can_use_weight"]).sum()),
            int((~products["can_calculate_volume"]).sum()),
        ],
        "销售明细数": [
            int(joined["flag_category_missing"].sum()),
            int(joined["flag_category_untranslated"].sum()),
            int((~joined["can_use_weight"]).sum()),
            int((~joined["can_calculate_volume"]).sum()),
        ],
    }, index=["原始品类缺失", "有品类但无翻译", "重量不满足基础条件", "体积不可计算"])


def summarize_product_metrics(products, translation, joined):
    """只汇总实际观察值；无可用体积时统计量返回 None，而不是零。"""
    volume = products["product_volume_cm3"].dropna()
    return {
        "product_rows": int(len(products)),
        "translation_rows": int(len(translation)),
        "original_category_count": int(products["product_category_name"].nunique()),
        "category_matched_products": int(products["category_match"].eq("both").sum()),
        "category_missing_products": int(products["flag_category_missing"].sum()),
        "category_untranslated_products": int(products["flag_category_untranslated"].sum()),
        "english_category_missing_products": int(products["product_category_name_english"].isna().sum()),
        "content_metadata_missing_products": int(products["flag_content_metadata_missing"].sum()),
        "weight_missing_products": int(products["flag_weight_missing"].sum()),
        "weight_zero_products": int(products["flag_weight_zero"].sum()),
        "usable_weight_products": int(products["can_use_weight"].sum()),
        "dimensions_missing_products": int(products["flag_dimensions_missing"].sum()),
        "dimensions_nonpositive_products": int(products["flag_dimensions_nonpositive"].sum()),
        "volume_eligible_products": int(products["can_calculate_volume"].sum()),
        "volume_unknown_products": int(products["product_volume_cm3"].isna().sum()),
        "volume_min_cm3": int(volume.min()) if len(volume) else None,
        "volume_median_cm3": float(volume.median()) if len(volume) else None,
        "volume_mean_cm3": float(volume.mean()) if len(volume) else None,
        "volume_max_cm3": int(volume.max()) if len(volume) else None,
        "item_rows": int(len(joined)),
        "item_orders": int(joined["order_id"].nunique()),
        "item_product_ids": int(joined["product_id"].nunique()),
        "item_primary_key_duplicates": int(joined.duplicated(ITEM_KEY_COLS).sum()),
        "items_without_product": int(joined["products_match"].eq("left_only").sum()),
        "unused_products": int((~products["product_id"].isin(joined["product_id"])).sum()),
        "goods_cents": int(joined["price_cents"].sum()),
        "freight_cents": int(joined["freight_cents"].sum()),
        "item_lines_missing_category": int(joined["flag_category_missing"].sum()),
        "item_lines_untranslated_category": int(joined["flag_category_untranslated"].sum()),
        "item_lines_without_usable_weight": int((~joined["can_use_weight"]).sum()),
        "item_lines_without_volume": int((~joined["can_calculate_volume"]).sum()),
    }
