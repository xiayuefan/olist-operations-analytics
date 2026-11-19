"""Q23–Q24 用逻辑回归比较延迟订单与按时或提前订单的低评分表现。"""

import argparse
from pathlib import Path
from warnings import catch_warnings, simplefilter

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression

from reviews_cleaning import select_latest_reviews


INPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "processed" / "mysql_input_v1"


def load_analysis_sample():
    orders = pd.read_parquet(INPUT_DIR / "orders.parquet", columns=[
        "order_id", "customer_id", "order_status", "order_purchase_timestamp",
        "is_valid_delay", "delivery_delay_days",
    ])
    customers = pd.read_parquet(INPUT_DIR / "customers.parquet", columns=[
        "customer_id", "customer_state",
    ])
    reviews = pd.read_parquet(INPUT_DIR / "order_reviews.parquet", columns=[
        "order_id", "review_id", "review_score", "review_answer_timestamp",
        "flag_answer_before_creation",
    ])

    purchase_at = orders["order_purchase_timestamp"]
    eligible = orders.loc[
        orders["order_status"].eq("delivered")
        & purchase_at.ge("2017-01-01")
        & purchase_at.lt("2018-09-01")
        & orders["is_valid_delay"]
        & orders["delivery_delay_days"].notna()
    ]
    # 先把评价缩到一行一单。内关联留下有有效评分的订单。
    latest = select_latest_reviews(reviews)[["order_id", "review_score"]]
    sample = eligible.merge(latest, on="order_id", validate="one_to_one")
    sample = sample.merge(customers, on="customer_id", how="left", validate="many_to_one")
    if sample["customer_state"].isna().any():
        raise ValueError("有分析订单缺少客户州，请检查订单与客户表的关联")

    sample["is_late"] = sample["delivery_delay_days"].gt(0).astype(int)
    sample["low_score"] = sample["review_score"].isin([1, 2]).astype(int)
    sample["purchase_month"] = sample["order_purchase_timestamp"].dt.strftime("%Y-%m")
    return sample


def add_main_category(sample):
    items = pd.read_parquet(INPUT_DIR / "order_items.parquet", columns=[
        "order_id", "product_id", "price_cents",
    ])
    products = pd.read_parquet(INPUT_DIR / "products.parquet", columns=[
        "product_id", "product_category_name",
    ])
    items = items.loc[items["order_id"].isin(sample["order_id"])].merge(
        products, on="product_id", how="left", validate="many_to_one"
    )
    items["product_category_name"] = items["product_category_name"].fillna("(unknown_category)")

    # 先汇总每单各品类的商品金额，再取金额最高的品类。并列时按品类名排序。
    amounts = items.groupby(["order_id", "product_category_name"], as_index=False)["price_cents"].sum()
    main = amounts.sort_values(
        ["order_id", "price_cents", "product_category_name"], ascending=[True, False, True]
    ).drop_duplicates("order_id")
    result = sample.merge(main[["order_id", "product_category_name"]],
                          on="order_id", how="left", validate="one_to_one")

    # 品类组计数以订单为单位。保留未知品类，并把不足 50 单的已知品类合并。
    category = result["product_category_name"].fillna("(unknown_category)")
    category_counts = category.map(category.value_counts())
    result["main_category"] = category.mask(
        category.ne("(unknown_category)") & category_counts.lt(50), "(other_small_categories)"
    )
    return result.drop(columns="product_category_name")


def summarize_model(model_name, features, outcome):
    model = LogisticRegression(penalty=None, solver="newton-cholesky", tol=1e-10, max_iter=100)
    with catch_warnings():
        simplefilter("error", ConvergenceWarning)
        model.fit(features, outcome)

    # exp(延迟系数) 是优势比。is_late 是 0/1，0 表示按时或提前。
    coefficient = model.coef_[0, features.columns.get_loc("is_late")]

    # 固定同一批订单的其余变量，只切换 is_late 后计算平均拟合概率。
    on_time_pct = 100 * model.predict_proba(features.assign(is_late=0))[:, 1].mean()
    late_pct = 100 * model.predict_proba(features.assign(is_late=1))[:, 1].mean()
    return {
        "model": model_name,
        "rated_orders": len(outcome),
        "late_odds_ratio": np.exp(coefficient),
        "on_time_low_score_pct": on_time_pct,
        "late_low_score_pct": late_pct,
        "low_score_gap_pp": late_pct - on_time_pct,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-category", action="store_true", help="加入 Q24 的主品类模型")
    args = parser.parse_args()

    sample = load_analysis_sample()
    if args.include_category:
        sample = add_main_category(sample)
    outcome = sample["low_score"]
    late_only = sample[["is_late"]]
    # 州和月份是类别。每种变量留一个参照类别，避免与截距重复。
    controls = pd.get_dummies(sample[["customer_state", "purchase_month"]],
                              drop_first=True, dtype=int)
    adjusted = pd.concat([late_only, controls], axis=1)
    results = [
        summarize_model("delay_only", late_only, outcome),
        summarize_model("state_and_month", adjusted, outcome),
    ]
    if args.include_category:
        category_controls = pd.get_dummies(sample[["main_category"]], drop_first=True, dtype=int)
        with_category = pd.concat([adjusted, category_controls], axis=1)
        results.append(summarize_model("state_month_and_category", with_category, outcome))
    print(pd.DataFrame(results).to_string(index=False, float_format="{:.2f}".format))


if __name__ == "__main__":
    main()
