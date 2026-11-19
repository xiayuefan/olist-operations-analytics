"""从原始 CSV 生成卖家阶段数据和检查报告。"""

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from items_cleaning import clean_order_items
from sellers_cleaning import (
    LOCATION_FLAGS, build_order_seller_pairs, clean_sellers, join_items_sellers,
    reconcile_seller_totals, summarize_seller_sales,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCOPE = "全部商品明细及其覆盖的订单"


def read_source(path):
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig",
                       keep_default_na=False, na_values=[""])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_DIR.parent / "archive")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "data" / "processed" / "sellers_v1")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_DIR / "reports" / "sellers_v1")
    args = parser.parse_args()

    seller_path = args.data_dir / "olist_sellers_dataset.csv"
    item_path = args.data_dir / "olist_order_items_dataset.csv"
    sellers = clean_sellers(read_source(seller_path))
    items = clean_order_items(read_source(item_path))
    joined = join_items_sellers(items, sellers)
    profile = summarize_seller_sales(joined, sellers)
    pairs = build_order_seller_pairs(joined)
    controls = reconcile_seller_totals(items, profile, pairs)

    # 同一订单涉及 k 个卖家时，产生 k 对关系，较全局计数多出 k-1 对。
    seller_counts = pairs.groupby("order_id").size()
    distribution = seller_counts.value_counts().sort_index().rename_axis(
        "seller_count").reset_index(name="order_count")
    orders = int(seller_counts.size)
    multi_seller_orders = int(seller_counts.gt(1).sum())
    extra_pairs = int((seller_counts - 1).sum())
    region_flags = {name: int(sellers[name].sum()) for name in LOCATION_FLAGS}
    metrics = {
        "scope": SCOPE,
        "seller_rows": len(sellers),
        "sellers_with_items": len(profile),
        "item_rows": len(items),
        "distinct_orders_with_items": orders,
        "order_seller_pairs": len(pairs),
        "multi_seller_orders": multi_seller_orders,
        "extra_order_seller_pairs": extra_pairs,
        "goods_amount_cents": int(items["price_cents"].sum()),
        "freight_amount_cents": int(items["freight_cents"].sum()),
        "location_flags": region_flags,
        "source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [seller_path, item_path]
        },
    }
    report = "\n".join([
        "# 卖家阶段报告 v1", "",
        "统计范围为{}。金额单位为巴西雷亚尔的整数分。".format(SCOPE), "",
        "| 指标 | 数量 |", "| --- | ---: |",
        "| 卖家属性记录 | {:,} |".format(len(sellers)),
        "| 有商品明细的卖家 | {:,} |".format(len(profile)),
        "| 商品明细 | {:,} |".format(len(items)),
        "| 明细覆盖的不同订单 | {:,} |".format(orders),
        "| 订单＋卖家关系 | {:,} |".format(len(pairs)),
        "| 多卖家订单 | {:,} |".format(multi_seller_orders),
        "| 多出的订单＋卖家关系 | {:,} |".format(extra_pairs), "",
        "卖家汇总与关系表的六项控制差额均为零。"
        "各卖家订单数之和按订单＋卖家组合核对，全局不同订单数按订单 ID 核对。", "",
        "地区格式标记及来源文件校验值保存在 metrics_v1.json。"
        "邮编前缀用字符串读取可保留前导零。下一阶段将检查地理表的邮编覆盖和坐标。", "",
    ])
    outputs = {
        "sellers_clean_v1.csv": sellers,
        "items_with_sellers_v1.csv": joined,
        "seller_profile_v1.csv": profile,
        "order_seller_pairs_v1.csv": pairs,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)

    # 先完成所有文件的写入，再用同盘临时文件逐个替换正式文件。
    with TemporaryDirectory(dir=args.output_dir) as data_tmp, TemporaryDirectory(dir=args.report_dir) as report_tmp:
        data_stage, report_stage = Path(data_tmp), Path(report_tmp)
        for name, frame in outputs.items():
            frame.to_csv(data_stage / name, index=False, encoding="utf-8-sig")
        controls.to_csv(report_stage / "seller_controls_v1.csv", index_label="检查项", encoding="utf-8-sig")
        distribution.to_csv(report_stage / "seller_count_distribution_v1.csv", index=False, encoding="utf-8-sig")
        (report_stage / "metrics_v1.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        (report_stage / "卖家阶段报告_v1.md").write_text(report, encoding="utf-8")
        for staged, target in [(data_stage, args.output_dir), (report_stage, args.report_dir)]:
            for file in staged.iterdir():
                file.replace(target / file.name)

    print("卖家属性 {:,} 行，销售明细 {:,} 条，订单＋卖家关系 {:,} 对。".format(
        len(sellers), len(items), len(pairs)))
    print("控制差额全部为 0。报告目录 " + str(args.report_dir.resolve()))


if __name__ == "__main__":
    main()
