"""评价阶段 v1：明细保留、每单最新评价、订单聚合与覆盖核对。

兼容 Python 3.7+ / Pandas 1.1+。重点关注每一步的粒度：
原始/清洗表是一行一条评价；最新评价与汇总表是一行一个订单。
"""

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype

from orders_cleaning import ORDER_STATUSES


REVIEW_KEY_COLS = ["order_id", "review_id"]
TIME_COLS = ["review_creation_date", "review_answer_timestamp"]
TIME_FLAG_COLS = [
    "flag_missing_creation_date", "flag_missing_answer_timestamp",
    "flag_answer_before_creation",
]
SUMMARY_INT_COLS = [
    "review_record_count", "low_score_record_count", "latest_review_score",
]
SUMMARY_BOOL_COLS = ["any_low_score", "latest_is_low_score", "rules_disagree"]
SUMMARY_COLS = [
    "review_record_count", "low_score_record_count", "any_low_score",
    "latest_review_id", "latest_review_score", "latest_review_answer_timestamp",
    "latest_is_low_score", "rules_disagree",
]


def _require_columns(frame, cols, label):
    missing = sorted(set(cols) - set(frame.columns))
    if missing:
        raise ValueError(label + "缺少列：" + ", ".join(missing))
    if frame.empty:
        raise ValueError(label + "为空，请检查输入")


def _check_key(frame, cols, label):
    _require_columns(frame, cols, label)
    for col in cols:
        if frame[col].isna().any() or frame[col].astype(str).str.strip().eq("").any():
            raise ValueError(label + "存在缺失或空白主键：" + col)
    if frame.duplicated(cols).any():
        raise ValueError(label + "主键重复，请核查；不自动删除记录")


def check_review_keys(raw):
    """分别检查单列、组合键和整行；重复 review_id 不等于重复整行。"""
    _require_columns(raw, REVIEW_KEY_COLS, "评价原表")
    return pd.Series({
        "评价记录行数": len(raw),
        "评价ID不同值数": raw["review_id"].nunique(),
        "涉及订单数": raw["order_id"].nunique(),
        "评价ID缺失行数": raw["review_id"].isna().sum(),
        "订单ID缺失行数": raw["order_id"].isna().sum(),
        "评价ID重复行数_首条之后": raw.duplicated(["review_id"]).sum(),
        "订单ID重复行数_首条之后": raw.duplicated(["order_id"]).sum(),
        "组合主键重复行数_首条之后": raw.duplicated(REVIEW_KEY_COLS).sum(),
        "整行重复数_首条之后": raw.duplicated().sum(),
    }, name="数量")


def clean_order_reviews(raw_reviews):
    """返回完整工作副本，不删除多评记录或无文字评论。"""
    required = REVIEW_KEY_COLS + [
        "review_score", "review_comment_title", "review_comment_message",
    ] + TIME_COLS
    _require_columns(raw_reviews, required, "评价原表")
    # 只要求组合键唯一：同一个订单可以有不同评价，同一个评价 ID 也可能出现在不同订单。
    _check_key(raw_reviews, REVIEW_KEY_COLS, "评价原表")
    cleaned = raw_reviews.copy()

    # 评分先检查再转型。遇到无效评分停止，避免把缺失或异常评分误标为“非低分”。
    score = pd.to_numeric(raw_reviews["review_score"], errors="coerce")
    if not score.isin([1, 2, 3, 4, 5]).all():
        raise ValueError("评分应为非空的 1～5 整数，请先核查")
    cleaned["review_score"] = score.astype("Int64")
    cleaned["is_low_score"] = cleaned["review_score"].le(2)

    # fillna 只出现在临时判断表达式中；原始评论正文、标题都保留。
    # strip 后为空也算“没有有效文字”，因此能识别只有空格的评论。
    for source, flag in [
        ("review_comment_title", "has_comment_title"),
        ("review_comment_message", "has_comment_message"),
    ]:
        cleaned[flag] = raw_reviews[source].fillna("").str.strip().ne("")

    for col in TIME_COLS:
        parsed = pd.to_datetime(
            raw_reviews[col], format="%Y-%m-%d %H:%M:%S", errors="coerce")
        if (raw_reviews[col].notna() & parsed.isna()).any():
            raise ValueError(col + "存在非空但无法解析的值，请先核查")
        cleaned[col] = parsed

    # 时间缺失先保留并标记；缺少创建时间不妨碍按已知提交时间排序。
    cleaned["flag_missing_creation_date"] = cleaned["review_creation_date"].isna()
    cleaned["flag_missing_answer_timestamp"] = cleaned["review_answer_timestamp"].isna()
    cleaned["can_compare_review_time"] = cleaned[TIME_COLS].notna().all(axis=1)
    cleaned["flag_answer_before_creation"] = (
        cleaned["can_compare_review_time"]
        & cleaned["review_answer_timestamp"].lt(cleaned["review_creation_date"]))
    cleaned["flag_review_time_needs_review"] = cleaned[TIME_FLAG_COLS].any(axis=1)

    # 这是提交距创建的间隔，包含等待时间，不是实际填写问卷的用时。
    valid_interval = cleaned["can_compare_review_time"] & ~cleaned["flag_answer_before_creation"]
    cleaned["review_answer_lag_days"] = (
        (cleaned["review_answer_timestamp"] - cleaned["review_creation_date"])
        .dt.total_seconds().div(86400).where(valid_interval))
    return cleaned


def select_latest_reviews(cleaned):
    """每单按最大提交时间筛选一条；明细原表仍保留全部记录。"""
    _require_columns(cleaned, REVIEW_KEY_COLS + [
        "review_score", "review_answer_timestamp", "flag_answer_before_creation",
    ], "评价工作表")
    _check_key(cleaned, REVIEW_KEY_COLS, "评价工作表")
    if not is_datetime64_any_dtype(cleaned["review_answer_timestamp"].dtype):
        raise ValueError("请先将提交时间转换为日期时间类型")
    # 若某条记录的提交时间未知，无法确认它是不是该订单最新的一条。
    # 当前数据这两类问题均为 0；未来遇到时先停止核查，不猜测最新评价。
    if cleaned["review_answer_timestamp"].isna().any() or cleaned["flag_answer_before_creation"].any():
        raise ValueError("提交时间缺失或早于创建日期，须先核查后才能确定最新评价")

    # transform 给每一行附上“同一订单的最大提交时间”，此处尚未减少行数。
    latest_time = cleaned.groupby("order_id")["review_answer_timestamp"].transform("max")
    # 真正筛选发生在 loc：只保留时间等于该订单最大时间的记录。
    latest = cleaned.loc[cleaned["review_answer_timestamp"].eq(latest_time)].copy()
    tie_orders = int(latest["order_id"].value_counts().gt(1).sum())
    if tie_orders:
        raise ValueError("有 {} 笔订单最新提交时间并列，需要先制定取值规则".format(tie_orders))
    return latest


def aggregate_order_reviews(cleaned, latest):
    """将全部明细聚合，再连接每单最新评价；结果一行一个订单。"""
    _require_columns(cleaned, REVIEW_KEY_COLS + [
        "review_score", "is_low_score", "review_answer_timestamp",
    ], "评价工作表")
    _check_key(cleaned, REVIEW_KEY_COLS, "评价工作表")
    _require_columns(latest, REVIEW_KEY_COLS + [
        "review_score", "review_answer_timestamp",
    ], "最新评价表")
    _check_key(latest, ["order_id"], "最新评价表")
    if set(latest["order_id"]) != set(cleaned["order_id"]):
        raise ValueError("最新评价未完整覆盖评价订单，或存在额外订单")

    # 防止手工传入旧评价或错误字段：选择结果必须能追溯到同一原始明细。
    fields = REVIEW_KEY_COLS + ["review_score", "review_answer_timestamp"]
    verified = latest[fields].merge(
        cleaned[fields], on=REVIEW_KEY_COLS, how="left",
        validate="one_to_one", indicator=True, suffixes=("_selected", "_source"))
    if (not verified["_merge"].eq("both").all()
            or not verified["review_score_selected"].eq(verified["review_score_source"]).all()
            or not verified["review_answer_timestamp_selected"].eq(
                verified["review_answer_timestamp_source"]).all()):
        raise ValueError("最新评价与原始评价明细无法对应，请核查")
    expected_latest = cleaned.groupby("order_id")["review_answer_timestamp"].max()
    if not latest["review_answer_timestamp"].eq(latest["order_id"].map(expected_latest)).all():
        raise ValueError("传入的评价并非每单最大提交时间对应的记录")

    # groupby + agg 在这里把同一订单的多条评价合成一行。
    # size 数全部记录；sum 数低评分记录；any 判断是否至少一次低评分。
    # low_score_record_count 保留记录级数量，可用于解释 14575 与 14533 的差别。
    stats = cleaned.groupby("order_id", as_index=False).agg(
        review_record_count=("review_id", "size"),
        low_score_record_count=("is_low_score", "sum"),
        any_low_score=("is_low_score", "any"),
    )
    latest_result = latest[fields].rename(columns={
        "review_id": "latest_review_id",
        "review_score": "latest_review_score",
        "review_answer_timestamp": "latest_review_answer_timestamp",
    })
    # 两侧已经各自是一行一个订单；validate 负责检查，不负责去重。
    summary = stats.merge(latest_result, on="order_id", how="left", validate="one_to_one")
    summary["latest_is_low_score"] = summary["latest_review_score"].le(2).astype("boolean")
    summary["rules_disagree"] = summary["any_low_score"].ne(summary["latest_is_low_score"])
    return summary


def join_orders_reviews(raw_orders, summary):
    """将订单级评价左连接回全部订单；无评价的评分与布尔标记保持未知。"""
    _require_columns(raw_orders, ["order_id", "order_status"], "订单原表")
    _check_key(raw_orders, ["order_id"], "订单原表")
    _require_columns(summary, ["order_id"] + SUMMARY_COLS, "评价汇总")
    _check_key(summary, ["order_id"], "评价汇总")
    if not raw_orders["order_status"].isin(ORDER_STATUSES).all():
        raise ValueError("订单状态缺失或未知，请核查")
    if summary[SUMMARY_COLS].isna().any().any():
        raise ValueError("评价汇总内部存在缺失，须先核查再关联")
    if (~summary["order_id"].isin(raw_orders["order_id"])).any():
        raise ValueError("评价汇总中存在找不到订单主表的订单")
    if set(SUMMARY_COLS + ["reviews_match", "flag_missing_reviews"]) & set(raw_orders.columns):
        raise ValueError("输入已包含评价关联字段，请使用订单原表")

    right = summary[["order_id"] + SUMMARY_COLS].copy()
    # 关联前规范成可空类型，未匹配行才能同时保留整数/布尔语义与 <NA>。
    for col in SUMMARY_INT_COLS:
        right[col] = right[col].astype("Int64")
    for col in SUMMARY_BOOL_COLS:
        right[col] = right[col].astype("boolean")
    right["latest_review_id"] = right["latest_review_id"].astype("string")
    joined = raw_orders.copy().merge(
        right, on="order_id", how="left", validate="one_to_one", indicator="reviews_match")
    joined["flag_missing_reviews"] = joined["reviews_match"].eq("left_only")
    return joined


def reconcile_review_totals(cleaned, latest, summary, joined):
    """记录数通过计数列求和核对，不能要求聚合前后的表行数相等。"""
    checks = pd.DataFrame({
        "明细层": [
            len(cleaned), int(cleaned["is_low_score"].sum()),
            cleaned["order_id"].nunique(), len(latest),
        ],
        "订单汇总层": [
            int(summary["review_record_count"].sum()), int(summary["low_score_record_count"].sum()),
            len(summary), int(summary["latest_review_score"].notna().sum()),
        ],
        "关联后": [
            int(joined["review_record_count"].sum()), int(joined["low_score_record_count"].sum()),
            int(joined["reviews_match"].eq("both").sum()),
            int(joined["latest_review_score"].notna().sum()),
        ],
    }, index=["评价记录数", "低评分评价记录数", "有评价订单数", "最新评价对应订单数"])
    checks["汇总差额"] = checks["订单汇总层"] - checks["明细层"]
    checks["关联差额"] = checks["关联后"] - checks["订单汇总层"]
    if checks[["汇总差额", "关联差额"]].ne(0).any().any():
        raise ValueError("评价记录或订单数量在汇总、关联后变化，请核查")
    return checks


def compare_review_rules(summary):
    """当前基线使用同一批有有效评价的订单比较两种规则。"""
    _require_columns(summary, ["order_id"] + SUMMARY_BOOL_COLS, "评价汇总")
    if summary[SUMMARY_BOOL_COLS].isna().any().any():
        raise ValueError("规则比较前须明确两个规则的有效样本")
    comparison = pd.DataFrame({
        "低评分订单数": [
            int(summary["latest_is_low_score"].sum()), int(summary["any_low_score"].sum()),
        ],
        "有有效评价订单数": [len(summary), len(summary)],
    }, index=["最新有效评分", "任意一次低评分"])
    comparison["低评分比例（%）"] = (
        comparison["低评分订单数"] / comparison["有有效评价订单数"] * 100).round(2)
    return comparison


def check_review_text(raw):
    """区分原始缺失与非空但只含空白字符，两者均不算有效文字。"""
    results = {}
    for col in ["review_comment_title", "review_comment_message"]:
        has_text = raw[col].fillna("").str.strip().ne("")
        results[col] = {
            "原始缺失数": int(raw[col].isna().sum()),
            "非空但只有空白字符数": int((raw[col].notna() & ~has_text).sum()),
            "无有效文字记录数": int((~has_text).sum()),
            "有有效文字记录数": int(has_text.sum()),
        }
    return pd.DataFrame(results).T


def check_review_dates(raw, cleaned):
    return pd.DataFrame({
        col: {
            "原始缺失数": int(raw[col].isna().sum()),
            "非空但解析失败数": int((raw[col].notna() & cleaned[col].isna()).sum()),
            "转换后类型": str(cleaned[col].dtype),
        } for col in TIME_COLS
    }).T


def summarize_review_metrics(cleaned, latest, summary, joined):
    """计数转换为 Python 整数，方便保存 JSON；比例均注明订单级分母。"""
    low_counts = cleaned.loc[cleaned["is_low_score"], "order_id"].value_counts()
    lag = cleaned["review_answer_lag_days"].dropna()
    return {
        "review_rows": int(len(cleaned)),
        "review_id_unique": int(cleaned["review_id"].nunique()),
        "review_id_duplicate_rows": int(cleaned.duplicated(["review_id"]).sum()),
        "reviewed_orders": int(len(summary)),
        "multi_review_orders": int(summary["review_record_count"].gt(1).sum()),
        "max_reviews_per_order": int(summary["review_record_count"].max()),
        "low_score_review_rows": int(cleaned["is_low_score"].sum()),
        "any_low_score_orders": int(summary["any_low_score"].sum()),
        "latest_low_score_orders": int(summary["latest_is_low_score"].sum()),
        "latest_review_rows": int(len(latest)),
        "rules_disagree_orders": int(summary["rules_disagree"].sum()),
        "orders_with_multiple_low_reviews": int(low_counts.gt(1).sum()),
        "extra_low_review_rows": int((low_counts - 1).sum()),
        "latest_low_score_rate": int(summary["latest_is_low_score"].sum()) / len(summary),
        "any_low_score_rate": int(summary["any_low_score"].sum()) / len(summary),
        "no_title_rows": int((~cleaned["has_comment_title"]).sum()),
        "no_message_rows": int((~cleaned["has_comment_message"]).sum()),
        "missing_creation_rows": int(cleaned["flag_missing_creation_date"].sum()),
        "missing_answer_rows": int(cleaned["flag_missing_answer_timestamp"].sum()),
        "answer_before_creation_rows": int(cleaned["flag_answer_before_creation"].sum()),
        "mean_answer_lag_days": float(lag.mean()) if len(lag) else None,
        "median_answer_lag_days": float(lag.median()) if len(lag) else None,
        "max_answer_lag_days": float(lag.max()) if len(lag) else None,
        "all_order_rows": int(len(joined)),
        "orders_without_reviews": int(joined["flag_missing_reviews"].sum()),
        "delivered_without_reviews": int((
            joined["flag_missing_reviews"] & joined["order_status"].eq("delivered")).sum()),
    }
