"""为 Power BI 结课课件导出可复现的 Parquet 输入和对照值。"""

import importlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from reviews_cleaning import select_latest_reviews


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "processed" / "mysql_input_v1"
OUTPUT = ROOT / "data" / "processed" / "powerbi_v1"
START = pd.Timestamp("2017-01-01")
END = pd.Timestamp("2018-09-01")  # 右边界不含当天；同时作为 RFM 历史基准日。
BANDS = ["按时或提前", "延迟 1–3 天", "延迟 4–7 天", "延迟 8–14 天", "延迟 15 天及以上"]


def read_table(name, columns):
    return pd.read_parquet(SOURCE / f"{name}.parquet", columns=columns)


def build_order_insights(orders):
    """一行一单；增加评价和分段字段，保留无评价和无法判断的订单。"""
    reviews = read_table("order_reviews", ["order_id", "review_id", "review_score",
                                           "review_answer_timestamp", "flag_answer_before_creation"])
    latest = select_latest_reviews(reviews)[["order_id", "review_score"]]
    result = orders[["order_id"]].copy()
    result["latest_review_score"] = result["order_id"].map(latest.set_index("order_id")["review_score"]).astype("Int64")

    # 与 Q18 一致。不可判断的订单既不归入提前档，也不归入延迟档。
    bands = pd.cut(orders["delivery_delay_days"].where(orders["is_valid_delay"]),
                  [-np.inf, 0, 3, 7, 14, np.inf], labels=BANDS)
    result["delay_band"] = bands.astype("string")
    result["delay_band_order"] = bands.cat.codes.add(1).where(bands.notna()).astype("Int64")

    # 每个阶段单独判断资格。前两个阶段需要端点齐全且先后正确，交承运商时长
    # 还要求审批发生在下单后。运输直接使用清洗层验证过的字段。
    delivered = orders["order_status"].eq("delivered")
    purchase = orders["order_purchase_timestamp"]
    approved = orders["order_approved_at"]
    carrier = orders["order_delivered_carrier_date"]
    approval_ok = delivered & approved.ge(purchase)
    result["approval_days"] = (approved - purchase).dt.total_seconds().div(86400).where(approval_ok)
    result["handoff_days"] = (carrier - approved).dt.total_seconds().div(86400).where(
        approval_ok & carrier.ge(approved)
    )
    return result


def build_product_categories():
    products = read_table("products", ["product_id", "product_category_name"])
    translation = read_table("category_translation", ["product_category_name", "product_category_name_english"])
    products = products.merge(translation, how="left", on="product_category_name", validate="many_to_one")
    key = products["product_category_name"]
    english = products["product_category_name_english"]
    products["category_mapping"] = np.select(
        [key.isna(), english.isna()], ["source_missing", "translation_missing"], default="translated"
    )
    products["category_key"] = key.fillna("(missing)")
    products["category_label"] = english.fillna(key).fillna("(missing)")
    return products[["product_id", "category_key", "category_label", "category_mapping"]]


def build_customer_snapshots(delivered, customers, items):
    purchases = delivered[["order_id", "customer_id", "order_purchase_timestamp"]].merge(
        customers[["customer_id", "customer_unique_id"]], on="customer_id", validate="one_to_one"
    )
    if len(purchases) != len(delivered) or purchases["customer_unique_id"].isna().any():
        raise ValueError("窗口内已交付订单无法完整匹配客户")
    amounts = items.groupby("order_id")["price_cents"].sum().rename("goods_cents")
    purchases = purchases.join(amounts, on="order_id").sort_values(
        ["customer_unique_id", "order_purchase_timestamp", "order_id"]
    )
    history = purchases.groupby("customer_unique_id", sort=False)
    rank = history.cumcount()
    purchase_at = purchases["order_purchase_timestamp"]

    # Q12 的订单月统计。首次指窗口内第一次已交付购买，非平台历史首次。
    monthly = pd.DataFrame({"purchase_month": purchase_at.dt.strftime("%Y-%m"), "first_orders": rank.eq(0),
                            "repeat_orders": rank.gt(0)}).groupby("purchase_month", as_index=False).sum()
    monthly["delivered_orders"] = monthly["first_orders"] + monthly["repeat_orders"]

    # Q15–Q16。客户任一订单无商品金额时，该客户的整个 M 保留未知。
    rfm = history.agg(last_purchase=("order_purchase_timestamp", "max"), frequency=("order_id", "size"),
                      priced_orders=("goods_cents", "count"), goods_cents=("goods_cents", "sum"))
    rfm["goods_cents"] = rfm["goods_cents"].where(rfm["priced_orders"].eq(rfm["frequency"])).astype("Int64")
    rfm["frequency_group"] = np.where(rfm["frequency"].eq(1), "one_time", "repeat")
    rfm["recency_group"] = np.where((END - rfm["last_purchase"].dt.normalize()).dt.days.le(90),
                                    "within_90d", "over_90d")
    # 离散 P75 等同 SQL CUME_DIST 首次达到 .75 的金额。同金额用同一门槛。
    def discrete_p75(values):
        ordered = values.dropna().sort_values()
        return ordered.iloc[(3 * len(ordered) + 3) // 4 - 1] if len(ordered) else pd.NA

    cutoffs = rfm.groupby("frequency_group")["goods_cents"].agg(discrete_p75).astype("Int64")
    rfm["m_cutoff_cents"] = rfm["frequency_group"].map(cutoffs)
    rfm["monetary_group"] = "below_p75"
    rfm.loc[rfm["goods_cents"].ge(rfm["m_cutoff_cents"]).fillna(False), "monetary_group"] = "at_or_above_p75"
    rfm.loc[rfm["goods_cents"].isna(), "monetary_group"] = "unknown_m"
    segments = rfm.groupby(["frequency_group", "recency_group", "monetary_group"], as_index=False).agg(
        m_cutoff_cents=("m_cutoff_cents", "first"), customer_count=("frequency", "size"),
        delivered_orders=("frequency", "sum"), goods_cents=("goods_cents", lambda values: values.sum(min_count=1)),
    )
    segments["goods_cents"] = segments["goods_cents"].astype("Int64")

    # Q14。下个时间戳按客户时间线计算。即使未成熟组里已经观察到第二单，
    # 也不发布该组复购人数和复购率，避免与完整随访组错误比较。
    first = purchase_at.loc[rank.eq(0)]
    second = history["order_purchase_timestamp"].shift(-1).loc[rank.eq(0)]
    groups = []
    for days in (30, 60, 90):
        deadline = first + pd.Timedelta(days=days)
        group = pd.DataFrame({"first_purchase_month": first.dt.strftime("%Y-%m"),
                              "eligible": deadline.lt(END), "repeat": second.le(deadline)})
        counts = group.groupby("first_purchase_month", as_index=False).agg(
            cohort_customers=("eligible", "size"), eligible_customers=("eligible", "sum"),
            repeat_customers=("repeat", "sum"),
        )
        counts["followup_days"] = days
        counts["pending_customers"] = counts["cohort_customers"] - counts["eligible_customers"]
        counts["repeat_customers"] = counts["repeat_customers"].astype("Int64").where(counts["pending_customers"].eq(0))
        groups.append(counts)
    cohort = pd.concat(groups, ignore_index=True).sort_values(["first_purchase_month", "followup_days"])
    return monthly, segments, cohort


def build_seller_snapshot():
    # 与 Q29–Q31 共用样本、标准化、种子以及规则比较的实现。
    pipeline = importlib.import_module("14_seller_clustering")
    metrics = pipeline.build_seller_metrics()
    qualified, scaled = pipeline.prepare_cluster_features(metrics)
    _, qualified["cluster"] = pipeline.compare_cluster_counts(scaled)
    _, rules = pipeline.summarize_rule_overlap(metrics, qualified)
    qualified["rule_candidate"] = rules
    pca = PCA(n_components=2, svd_solver="full")
    qualified[["pc1", "pc2"]] = pca.fit_transform(scaled)
    sellers = metrics.join(qualified[["cluster", "rule_candidate", "pc1", "pc2"]])
    sellers["cluster_label"] = "未达到样本门槛"
    for cluster in sorted(qualified["cluster"].unique()):
        sellers.loc[sellers["cluster"].eq(cluster), "cluster_label"] = f"簇 {cluster}"
    sellers["rule_candidate"] = sellers["rule_candidate"].eq(True)
    lookup = read_table("sellers", ["seller_id", "seller_state"])
    sellers = sellers.drop(columns="cluster").reset_index().merge(lookup, on="seller_id", validate="one_to_one")
    if len(sellers) != len(metrics):
        raise ValueError("存在未匹配的卖家")
    return sellers, pca.explained_variance_ratio_


def main():
    orders = read_table("orders", ["order_id", "customer_id", "order_status", "order_purchase_timestamp",
                                   "order_approved_at", "order_delivered_carrier_date", "transit_days",
                                   "is_valid_delay", "delivery_delay_days"])
    items = read_table("order_items", ["order_id", "product_id", "price_cents", "freight_cents"])
    customers = read_table("customers", ["customer_id", "customer_unique_id", "customer_state"])
    insights = build_order_insights(orders)
    products = build_product_categories()
    delivered = orders.loc[orders["order_status"].eq("delivered") & orders["order_purchase_timestamp"].ge(START)
                           & orders["order_purchase_timestamp"].lt(END)]
    monthly, rfm, cohort = build_customer_snapshots(delivered, customers, items)
    sellers, pca_variance = build_seller_snapshot()
    assets = {"order_insights": (insights, ["order_id"]), "product_categories": (products, ["product_id"]),
              "monthly_purchase": (monthly, ["purchase_month"]), "customer_rfm": (rfm, ["frequency_group", "recency_group", "monetary_group"]),
              "customer_cohort": (cohort, ["first_purchase_month", "followup_days"]), "seller_snapshot": (sellers, ["seller_id"])}
    if not items["product_id"].isin(products["product_id"]).all():
        raise ValueError("存在未匹配商品维度的明细")
    delivered_insights = delivered.join(insights.set_index("order_id"), on="order_id")
    valid = delivered_insights["delay_band"].notna()
    expected_valid = (delivered_insights["is_valid_delay"] & delivered_insights["delivery_delay_days"].notna()).fillna(False)
    if not valid.eq(expected_valid).all():
        raise ValueError("延迟分档覆盖与清洗层资格不一致")
    purchases_count = int(rfm["customer_count"].sum())
    if int(rfm["delivered_orders"].sum()) != len(delivered) or int(monthly["delivered_orders"].sum()) != len(delivered):
        raise ValueError("客户分层或月度购买订单数未通过订单级控制总额")
    if not cohort.groupby("followup_days")["cohort_customers"].sum().eq(purchases_count).all():
        raise ValueError("随访窗口未覆盖同一客户全集")
    if not cohort["repeat_customers"].isna().eq(cohort["pending_customers"].gt(0)).all():
        raise ValueError("未成熟组的复购人数必须留空")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, (frame, key) in assets.items():
        if frame[key].isna().any().any() or frame.duplicated(key).any():
            raise ValueError(f"{name} 的键为空或不唯一")
        target = OUTPUT / f"{name}.parquet"
        frame.to_parquet(target, index=False)
        pd.testing.assert_frame_equal(frame.reset_index(drop=True), pd.read_parquet(target))

    sales = items.loc[items["order_id"].isin(delivered["order_id"])]
    controls = {
        "rows": {name: len(frame) for name, (frame, _) in assets.items()},
        "delivered_orders": len(delivered), "goods_cents": int(sales["price_cents"].sum()),
        "freight_cents": int(sales["freight_cents"].sum()), "valid_delay_orders": int(valid.sum()),
        "late_orders": int(delivered_insights["delivery_delay_days"].gt(0).sum()),
        "rated_orders": int(delivered_insights["latest_review_score"].count()),
        "low_score_orders": int(delivered_insights["latest_review_score"].isin([1, 2]).sum()),
        "rfm_customers": purchases_count, "clustered_sellers": int(sellers["pc1"].count()),
        "rule_candidates": int(sellers["rule_candidate"].sum()), "pca_variance_ratio": pca_variance.tolist(),
    }
    manifest = json.dumps(controls, ensure_ascii=False, indent=2)
    (OUTPUT / "controls.json").write_text(manifest + "\n", encoding="utf-8")
    print(manifest)


if __name__ == "__main__":
    main()
