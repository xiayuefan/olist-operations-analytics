"""Q29–Q31 探索卖家聚类，并与跟进规则比较。"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from reviews_cleaning import select_latest_reviews


PROJECT_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_DIR / "data" / "processed" / "mysql_input_v1"
PCA_PATH = PROJECT_DIR / "reports" / "sellers_v1" / "seller_clusters_pca.png"
MIN_ORDERS = 50
REFERENCE_SEED = 42
PROFILE_K = 3


def build_seller_metrics():
    orders = pd.read_parquet(INPUT_DIR / "orders.parquet", columns=[
        "order_id", "order_status", "order_purchase_timestamp",
        "is_valid_delay", "delivery_delay_days",
    ])
    items = pd.read_parquet(INPUT_DIR / "order_items.parquet", columns=["order_id", "seller_id"])
    reviews = pd.read_parquet(INPUT_DIR / "order_reviews.parquet", columns=[
        "order_id", "review_id", "review_score", "review_answer_timestamp",
        "flag_answer_before_creation",
    ])

    # 先去重订单与卖家关系。一个订单只剩一对关系时，才属于单卖家订单。
    pairs = items.drop_duplicates()
    single_seller = pairs.loc[~pairs["order_id"].duplicated(keep=False)]
    delivered = orders.loc[
        orders["order_status"].eq("delivered")
        & orders["order_purchase_timestamp"].ge("2017-01-01")
        & orders["order_purchase_timestamp"].lt("2018-09-01")
    ]
    single = delivered.merge(single_seller, on="order_id", validate="one_to_one")
    latest = select_latest_reviews(reviews)[["order_id", "review_score"]]
    single = single.merge(latest, on="order_id", how="left", validate="one_to_one")

    # 两个比率单独判断资格。订单可以有可信的延迟天数，同时缺少评分。
    single["valid_delay"] = single["is_valid_delay"] & single["delivery_delay_days"].notna()
    single["late"] = single["valid_delay"] & single["delivery_delay_days"].gt(0)
    single["low_score"] = single["review_score"].isin([1, 2])
    metrics = single.groupby("seller_id").agg(
        single_seller_orders=("order_id", "size"),
        valid_delay_orders=("valid_delay", "sum"),
        late_orders=("late", "sum"),
        rated_orders=("review_score", "count"),
        low_score_orders=("low_score", "sum"),
    )
    return metrics


def compare_cluster_counts(features):
    diagnostics = []
    profile_labels = None
    # 同一个 K 用三个种子检查初始化是否容易改变分组。每个种子尝试 20 次初始化。
    with threadpool_limits(limits=1):
        for k in range(2, 6):
            labels_by_seed = {}
            for seed in (REFERENCE_SEED, 7, 2026):
                model = KMeans(n_clusters=k, n_init=20, random_state=seed)
                labels_by_seed[seed] = model.fit_predict(features)

            labels = labels_by_seed[REFERENCE_SEED]
            sizes = pd.Series(labels).value_counts()
            if len(sizes) != k:
                raise ValueError(f"K={k} 未形成 {k} 个非空簇，请检查特征是否有足够的不同值")
            diagnostics.append({
                "k": k,
                "silhouette": silhouette_score(features, labels),
                "min_seed_ari": min(adjusted_rand_score(labels, labels_by_seed[seed])
                                    for seed in (7, 2026)),
                "smallest_cluster": sizes.min(),
            })
            if k == PROFILE_K:
                profile_labels = labels
    return pd.DataFrame(diagnostics), profile_labels


def save_pca_plot(scaled_features, labels, output_path):
    from matplotlib.figure import Figure

    # 聚类标签来自三列标准化特征。PCA 只改变绘图坐标。
    pca = PCA(n_components=2, svd_solver="full")
    coordinates = pca.fit_transform(scaled_features)
    variance_pct = 100 * pca.explained_variance_ratio_

    figure = Figure(figsize=(8, 5.2), layout="constrained")
    ax = figure.subplots()
    colors = ("#0072B2", "#D55E00", "#009E73")
    markers = ("o", "^", "s")
    for cluster, (color, marker) in enumerate(zip(colors, markers)):
        members = coordinates[labels == cluster]
        ax.scatter(members[:, 0], members[:, 1], s=25, alpha=0.68,
                   color=color, marker=marker, edgecolors="none",
                   label=f"Cluster {cluster}  ·  {len(members)} sellers")

    ax.set_title(f"Seller clusters in PCA space (K={PROFILE_K})", loc="left", pad=12)
    ax.set_xlabel(f"PC1 ({variance_pct[0]:.2f}% of variance)")
    ax.set_ylabel(f"PC2 ({variance_pct[1]:.2f}% of variance)")
    ax.set_aspect("equal", adjustable="box")
    ax.set_axisbelow(True)
    ax.grid(alpha=0.22)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3, frameon=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180)
    return variance_pct


def summarize_rule_overlap(metrics, clustered_sellers):
    # Q27 的基线来自全部单卖家订单，包括未达到样本门槛的卖家。
    total_late = int(metrics["late_orders"].sum())
    total_valid = int(metrics["valid_delay_orders"].sum())
    total_low = int(metrics["low_score_orders"].sum())
    total_rated = int(metrics["rated_orders"].sum())

    # 和 Q27 一样用交叉相乘比较原始比率，避免展示时的舍入影响入选。
    above_late = clustered_sellers["late_orders"] * total_valid > (
        total_late * clustered_sellers["valid_delay_orders"]
    )
    above_low = clustered_sellers["low_score_orders"] * total_rated > (
        total_low * clustered_sellers["rated_orders"]
    )
    followup = (above_late & above_low).rename("rule_candidates")
    overlap = clustered_sellers.assign(rule_candidates=followup).groupby("cluster", as_index=False).agg(
        sellers=("rule_candidates", "size"),
        rule_candidates=("rule_candidates", "sum"),
    )
    overlap["rule_candidate_share_pct"] = 100 * overlap["rule_candidates"] / overlap["sellers"]
    return overlap, followup


def prepare_cluster_features(metrics):
    """返回通过双样本门槛的卖家及按相同顺序排列的三列标准化特征。"""
    qualified = metrics.loc[
        metrics["valid_delay_orders"].ge(MIN_ORDERS) & metrics["rated_orders"].ge(MIN_ORDERS)
    ].copy()
    if len(qualified) <= 5:
        raise ValueError("符合样本门槛的卖家过少，无法比较 K=2 至 K=5")

    # 订单量右偏，先用 log1p 缩小头部与其他卖家的数量级差距。
    # 两个比率以各自的有效订单数为分母。再把三列一起转换为标准分数。
    features = pd.DataFrame({
        "log_orders": np.log1p(qualified["single_seller_orders"]),
        "late_rate": qualified["late_orders"] / qualified["valid_delay_orders"],
        "low_score_rate": qualified["low_score_orders"] / qualified["rated_orders"],
    })
    return qualified, StandardScaler().fit_transform(features)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pca", action="store_true", help="导出 Q30 的 PCA 散点图")
    parser.add_argument("--compare-rules", action="store_true", help="对照 Q31 的聚类标签与跟进规则")
    args = parser.parse_args()

    metrics = build_seller_metrics()
    qualified, scaled_features = prepare_cluster_features(metrics)
    diagnostics, labels = compare_cluster_counts(scaled_features)
    qualified["cluster"] = labels
    profile = qualified.groupby("cluster", as_index=False).agg(
        sellers=("single_seller_orders", "size"),
        orders=("single_seller_orders", "sum"),
        median_orders=("single_seller_orders", "median"),
        valid_delay_orders=("valid_delay_orders", "sum"),
        late_orders=("late_orders", "sum"),
        rated_orders=("rated_orders", "sum"),
        low_score_orders=("low_score_orders", "sum"),
    )
    # 簇内比率按订单加总计算，分母分别保留。
    profile["late_rate_pct"] = 100 * profile["late_orders"] / profile["valid_delay_orders"]
    profile["low_score_rate_pct"] = 100 * profile["low_score_orders"] / profile["rated_orders"]

    print(f"all_sellers={len(metrics)}  eligible_sellers={len(qualified)}  "
          f"eligible_orders={qualified['single_seller_orders'].sum()}")
    print("\nK diagnostics (seed 42)")
    print(diagnostics.to_string(index=False, float_format="{:.3f}".format))
    print(f"\nCluster profile (K={PROFILE_K}, seed {REFERENCE_SEED})")
    columns = ["cluster", "sellers", "orders", "median_orders", "late_rate_pct", "low_score_rate_pct"]
    print(profile[columns].to_string(index=False, float_format="{:.2f}".format))

    if args.pca:
        variance_pct = save_pca_plot(scaled_features, labels, PCA_PATH)
        print(f"\nPCA explained variance  PC1={variance_pct[0]:.2f}%  "
              f"PC2={variance_pct[1]:.2f}%  cumulative={variance_pct.sum():.2f}%")
        print(f"PCA plot: {PCA_PATH}")

    if args.compare_rules:
        overlap, followup = summarize_rule_overlap(metrics, qualified)
        print(f"\nRule comparison (K={PROFILE_K}, seed {REFERENCE_SEED})")
        print(f"rule_candidates_total={followup.sum()}")
        print(overlap.to_string(index=False, float_format="{:.2f}".format))


if __name__ == "__main__":
    main()
