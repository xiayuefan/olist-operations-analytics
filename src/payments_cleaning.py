"""支付阶段 v1：精确金额、订单汇总、覆盖核查与跨表金额复核。

兼容 Python 3.7+ / Pandas 1.1+。金额单位为整数分，缺失金额保持未知。
"""

import pandas as pd
from pandas.api.types import is_bool_dtype, is_integer_dtype

from items_cleaning import SUMMARY_COLS as ITEM_SUMMARY_COLS
from items_cleaning import to_cents
from orders_cleaning import ORDER_STATUSES


PAYMENT_KEY_COLS = ["order_id", "payment_sequential"]
PAYMENT_TYPES = ["credit_card", "boleto", "voucher", "debit_card", "not_defined"]
PAYMENT_FLAG_COLS = [
    "flag_zero_payment", "flag_payment_type_not_defined", "flag_zero_installments",
]
SUMMARY_FLAG_COLS = [
    "has_zero_payment_record", "has_undefined_payment_type", "has_zero_installments",
]
PAYMENT_SUMMARY_COLS = [
    "payment_record_count", "payment_amount_cents",
] + SUMMARY_FLAG_COLS
AMOUNT_COLS = ["goods_amount_cents", "freight_amount_cents", "payment_amount_cents"]


def _require_columns(frame, cols, label):
    missing = sorted(set(cols) - set(frame.columns))
    if missing:
        raise ValueError(label + "缺少列：" + ", ".join(missing))
    if frame.empty:
        raise ValueError(label + "为空，请核查输入")


def _check_key(frame, cols, label):
    _require_columns(frame, cols, label)
    for col in cols:
        if frame[col].isna().any() or frame[col].astype(str).str.strip().eq("").any():
            raise ValueError(label + "存在缺失或空白主键：" + col)
    if frame.duplicated(cols).any():
        raise ValueError(label + "主键重复；不自动去重")


def _check_integer_values(frame, cols, label, positive_cols=()):
    for col in cols:
        if frame[col].isna().any() or not is_integer_dtype(frame[col].dtype):
            raise ValueError(label + "应为非空整数：" + col)
        if frame[col].lt(0).any() or (col in positive_cols and frame[col].eq(0).any()):
            raise ValueError(label + "整数取值不符合范围：" + col)


def clean_order_payments(raw_payments):
    """输入原始字符串表，返回带整数分和核查标记的副本。"""
    required = PAYMENT_KEY_COLS + ["payment_type", "payment_installments", "payment_value"]
    _require_columns(raw_payments, required, "支付原表")
    _check_key(raw_payments, PAYMENT_KEY_COLS, "支付原表")
    cleaned = raw_payments.copy()
    for col in ["payment_sequential", "payment_installments"]:
        numbers = pd.to_numeric(raw_payments[col], errors="coerce")
        if (numbers.isna().any()
                or numbers.isin([float("inf"), float("-inf")]).any()
                or numbers.mod(1).ne(0).any()
                or numbers.lt(0).any()
                or (col == "payment_sequential" and numbers.eq(0).any())):
            raise ValueError(col + "须为有效整数；序号大于零、期数大于等于零")
        cleaned[col] = numbers.astype("Int64")
    # 例如原始字符串 01 与 1 转换后可能产生组合键冲突。
    _check_key(cleaned, PAYMENT_KEY_COLS, "类型规范后的支付表")
    if not cleaned["payment_type"].isin(PAYMENT_TYPES).all():
        raise ValueError("支付方式缺失或出现当前规则未覆盖的标签，请核查")

    # 始终从原始字符串换算，不先经过浮点数；payment_value 保留原值。
    cleaned["payment_value_cents"] = raw_payments["payment_value"].map(to_cents).astype("int64")
    if cleaned["payment_value_cents"].lt(0).any():
        raise ValueError("支付金额为负，请核查后再汇总")
    cleaned["flag_zero_payment"] = cleaned["payment_value_cents"].eq(0)
    cleaned["flag_payment_type_not_defined"] = cleaned["payment_type"].eq("not_defined")
    cleaned["flag_zero_installments"] = cleaned["payment_installments"].eq(0)
    cleaned["flag_payment_needs_review"] = cleaned[PAYMENT_FLAG_COLS].any(axis=1)
    return cleaned


def aggregate_order_payments(cleaned):
    """一行一条支付记录汇总为一行一个订单；期数不参与金额相乘。"""
    _require_columns(cleaned, PAYMENT_KEY_COLS + ["payment_value_cents"] + PAYMENT_FLAG_COLS, "支付工作表")
    _check_key(cleaned, PAYMENT_KEY_COLS, "支付工作表")
    _check_integer_values(cleaned, ["payment_value_cents"], "支付工作表")
    for col in PAYMENT_FLAG_COLS:
        if cleaned[col].isna().any() or not is_bool_dtype(cleaned[col].dtype):
            raise ValueError("支付核查标记应为非空布尔值：" + col)
    return cleaned.groupby("order_id", as_index=False).agg(
        payment_record_count=("payment_sequential", "size"),
        payment_amount_cents=("payment_value_cents", "sum"),
        has_zero_payment_record=("flag_zero_payment", "any"),
        has_undefined_payment_type=("flag_payment_type_not_defined", "any"),
        has_zero_installments=("flag_zero_installments", "any"),
    )


def join_orders_payments(raw_orders, summary):
    """保留全部原始订单字段；支付汇总没有覆盖的金额和标记保持缺失。"""
    _require_columns(raw_orders, ["order_id", "order_status"], "订单原表")
    _check_key(raw_orders, ["order_id"], "订单原表")
    _require_columns(summary, ["order_id"] + PAYMENT_SUMMARY_COLS, "支付汇总")
    _check_key(summary, ["order_id"], "支付汇总")
    if not raw_orders["order_status"].isin(ORDER_STATUSES).all():
        raise ValueError("订单状态缺失或未知，请核查")
    if set(PAYMENT_SUMMARY_COLS + ["payments_match", "flag_missing_payments"]) & set(raw_orders.columns):
        raise ValueError("订单输入已包含支付关联字段，请使用订单原表")
    _check_integer_values(
        summary, ["payment_record_count", "payment_amount_cents"],
        "支付汇总", positive_cols=["payment_record_count"])
    for col in SUMMARY_FLAG_COLS:
        if summary[col].isna().any() or not is_bool_dtype(summary[col].dtype):
            raise ValueError("支付汇总标记应为非空布尔值：" + col)
    if (~summary["order_id"].isin(raw_orders["order_id"])).any():
        raise ValueError("支付汇总存在找不到订单主表的订单，请核查")

    right = summary[["order_id"] + PAYMENT_SUMMARY_COLS].copy()
    # 先使用可空类型再连接，避免整数金额因未匹配行而转成浮点数。
    for col in ["payment_record_count", "payment_amount_cents"]:
        right[col] = right[col].astype("Int64")
    for col in SUMMARY_FLAG_COLS:
        right[col] = right[col].astype("boolean")
    joined = raw_orders.copy().merge(
        right, on="order_id", how="left", validate="one_to_one", indicator="payments_match")
    joined["flag_missing_payments"] = joined["payments_match"].eq("left_only")
    return joined


def reconcile_payment_totals(cleaned, summary, joined):
    """支付明细、订单汇总及关联后三层控制总额，出现差额即停止。"""
    checks = pd.DataFrame({
        "明细层": [len(cleaned), int(cleaned["payment_value_cents"].sum())],
        "订单汇总层": [
            int(summary["payment_record_count"].sum()), int(summary["payment_amount_cents"].sum())],
        "关联后": [
            int(joined["payment_record_count"].sum()), int(joined["payment_amount_cents"].sum())],
    }, index=["支付记录数", "支付金额（分）"])
    checks["汇总差额"] = checks["订单汇总层"] - checks["明细层"]
    checks["关联差额"] = checks["关联后"] - checks["订单汇总层"]
    if checks[["汇总差额", "关联差额"]].ne(0).any().any():
        raise ValueError("支付记录数或金额在汇总、关联后变化，请核查")
    return checks


def reconcile_order_amounts(orders_with_payments, item_summary):
    """保留所有订单，区分金额一致、存在差额、缺少数据无法核对。"""
    _require_columns(orders_with_payments, [
        "order_id", "payment_record_count", "payment_amount_cents", "flag_missing_payments",
    ], "订单支付关联表")
    _check_key(orders_with_payments, ["order_id"], "订单支付关联表")
    _require_columns(item_summary, ["order_id"] + ITEM_SUMMARY_COLS, "商品汇总")
    _check_key(item_summary, ["order_id"], "商品汇总")
    _check_integer_values(
        item_summary, ITEM_SUMMARY_COLS, "商品汇总",
        positive_cols=["item_line_count", "product_count", "seller_count"])
    if set(ITEM_SUMMARY_COLS + ["items_match"]) & set(orders_with_payments.columns):
        raise ValueError("订单支付关联表已包含商品字段，请使用单独的支付关联结果")
    if (~item_summary["order_id"].isin(orders_with_payments["order_id"])).any():
        raise ValueError("商品汇总存在找不到订单主表的订单，请核查")

    right = item_summary[["order_id"] + ITEM_SUMMARY_COLS].copy()
    for col in ITEM_SUMMARY_COLS:
        right[col] = right[col].astype("Int64")
    joined = orders_with_payments.copy().merge(
        right, on="order_id", how="left", validate="one_to_one", indicator="items_match")
    for col in AMOUNT_COLS:
        joined[col] = joined[col].astype("Int64")
    joined["flag_missing_items"] = joined["items_match"].eq("left_only")
    joined["can_reconcile_amount"] = joined[AMOUNT_COLS].notna().all(axis=1)
    joined["items_total_cents"] = joined["goods_amount_cents"] + joined["freight_amount_cents"]
    joined["payment_difference_cents"] = joined["payment_amount_cents"] - joined["items_total_cents"]
    joined["abs_difference_cents"] = joined["payment_difference_cents"].abs()
    # 无法核对时标记为未知，不把未知归为“金额一致”。
    joined["flag_amount_mismatch"] = joined["payment_difference_cents"].ne(0).astype("boolean")
    joined["amount_reconcile_status"] = "无法核对"
    can = joined["can_reconcile_amount"]
    joined.loc[can, "amount_reconcile_status"] = "金额完全一致"
    joined.loc[can & joined["flag_amount_mismatch"].fillna(False), "amount_reconcile_status"] = "存在金额差额"
    for col in ITEM_SUMMARY_COLS:
        if int(item_summary[col].sum()) != int(joined[col].sum()):
            raise ValueError("商品关联后控制总额变化：" + col)
    return joined


def amount_difference_distribution(reconciled):
    """按方向、绝对大小分别分组；这些分组不是容差通过规则。"""
    sample = reconciled.loc[reconciled["can_reconcile_amount"]]
    diff = sample["payment_difference_cents"]
    absolute = diff.abs()
    return pd.DataFrame({
        "分类维度": ["方向", "方向", "大小", "大小", "大小"],
        "分组": ["支付额较大", "支付额较小", "绝对差额1分", "绝对差额2至99分", "绝对差额100分及以上"],
        "订单数": [
            int(diff.gt(0).sum()), int(diff.lt(0).sum()),
            int(absolute.eq(1).sum()), int(absolute.between(2, 99).sum()),
            int(absolute.ge(100).sum()),
        ],
    })


def summarize_payment_metrics(cleaned, summary, reconciled):
    """返回可 JSON 保存的 Python 整数；无可比样本时金额汇总返回 None。"""
    sample = reconciled.loc[reconciled["can_reconcile_amount"]]
    diff = sample["payment_difference_cents"]
    absolute = diff.abs()
    return {
        "payment_rows": int(len(cleaned)),
        "orders_with_payments": int(len(summary)),
        "all_order_rows": int(len(reconciled)),
        "orders_missing_payments": int(reconciled["flag_missing_payments"].sum()),
        "multi_payment_orders": int(summary["payment_record_count"].gt(1).sum()),
        "max_records_per_order": int(summary["payment_record_count"].max()),
        "zero_payment_rows": int(cleaned["flag_zero_payment"].sum()),
        "orders_with_zero_payment_record": int(summary["has_zero_payment_record"].sum()),
        "zero_payment_total_orders": int(summary["payment_amount_cents"].eq(0).sum()),
        "undefined_type_rows": int(cleaned["flag_payment_type_not_defined"].sum()),
        "zero_installment_rows": int(cleaned["flag_zero_installments"].sum()),
        "flagged_payment_rows": int(cleaned["flag_payment_needs_review"].sum()),
        "all_payment_cents": int(cleaned["payment_value_cents"].sum()),
        "orders_missing_items": int(reconciled["flag_missing_items"].sum()),
        "amount_comparable_orders": int(len(sample)),
        "amount_uncomparable_orders": int((~reconciled["can_reconcile_amount"]).sum()),
        "amount_equal_orders": int(diff.eq(0).sum()),
        "amount_mismatch_orders": int(diff.ne(0).sum()),
        "payment_greater_orders": int(diff.gt(0).sum()),
        "payment_smaller_orders": int(diff.lt(0).sum()),
        "abs_difference_1_cent": int(absolute.eq(1).sum()),
        "abs_difference_2_to_99_cents": int(absolute.between(2, 99).sum()),
        "abs_difference_ge_100_cents": int(absolute.ge(100).sum()),
        "comparable_payment_cents": int(sample["payment_amount_cents"].sum()) if len(sample) else None,
        "comparable_items_cents": int(sample["items_total_cents"].sum()) if len(sample) else None,
        "signed_difference_cents": int(diff.sum()) if len(sample) else None,
        "absolute_difference_cents": int(absolute.sum()) if len(sample) else None,
        "max_abs_difference_cents": int(absolute.max()) if len(sample) else None,
    }


def recheck_raw_order(raw_items, raw_payments, reconciled, order_id):
    """针对一笔可核对订单，独立从原始字符串重算四个金额并比对。"""
    rows = reconciled.loc[reconciled["order_id"].eq(order_id)]
    if len(rows) != 1 or not bool(rows.iloc[0]["can_reconcile_amount"]):
        raise ValueError("样本订单不存在、不唯一或缺少金额，无法复核")
    items = raw_items.loc[raw_items["order_id"].eq(order_id)]
    payments = raw_payments.loc[raw_payments["order_id"].eq(order_id)]
    if items.empty or payments.empty:
        raise ValueError("样本缺少原始商品明细或支付记录")
    goods = int(items["price"].map(to_cents).sum())
    freight = int(items["freight_value"].map(to_cents).sum())
    payment = int(payments["payment_value"].map(to_cents).sum())
    row = rows.iloc[0]
    checks = pd.DataFrame({
        "原始明细重算": [goods, freight, payment, payment - goods - freight],
        "订单级结果": [int(row[col]) for col in [
            "goods_amount_cents", "freight_amount_cents", "payment_amount_cents", "payment_difference_cents",
        ]],
    }, index=["商品金额（分）", "运费（分）", "支付金额（分）", "金额差额（分）"])
    checks["差值"] = checks["原始明细重算"] - checks["订单级结果"]
    if checks["差值"].ne(0).any():
        raise ValueError("原始明细重算与订单级结果不一致，请核查处理过程")
    return checks
