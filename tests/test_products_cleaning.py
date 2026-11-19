"""验证商品阶段的业务边界：缺失原因、指标资格、关联粒度和金额守恒。"""

import sys
import unittest
from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from items_cleaning import clean_order_items
from products_cleaning import (
    NUMERIC_COLS, clean_product_attributes, join_items_products,
    join_product_categories, reconcile_product_totals, summarize_product_metrics,
)


class ProductBusinessRules(unittest.TestCase):
    def setUp(self):
        self.raw = pd.DataFrame([
            ["P1", "cat_a", None, None, None, "0", "2", "3", "4"],
            ["P2", None, "5", "12", "1", None, None, None, None],
            ["P3", "cat_b", "6", "13", "2", "10", "2", "2", "2"],
        ], columns=["product_id", "product_category_name"] + NUMERIC_COLS)
        self.translation = pd.DataFrame({
            "product_category_name": ["cat_a"],
            "product_category_name_english": ["category_a"],
        })
        self.raw_items = pd.DataFrame([
            ["O1", "1", "P1", "S1", "2018-01-01 00:00:00", "10.01", "0.00"],
            ["O1", "2", "P1", "S1", "2018-01-01 00:00:00", "10.01", "1.00"],
            ["O2", "1", "P2", "S1", "2018-01-01 00:00:00", "5.00", "0.50"],
            ["O3", "1", "P3", "S1", "2018-01-01 00:00:00", "6.00", "0.60"],
        ], columns=["order_id", "order_item_id", "product_id", "seller_id",
                    "shipping_limit_date", "price", "freight_value"])

    def clean(self, raw=None, translation=None):
        return clean_product_attributes(join_product_categories(
            self.raw if raw is None else raw,
            self.translation if translation is None else translation))

    def test_category_reasons_are_distinct_and_inputs_unchanged(self):
        original = self.raw.copy(deep=True)
        original_translation = self.translation.copy(deep=True)
        products = self.clean()
        assert_frame_equal(self.raw, original)
        assert_frame_equal(self.translation, original_translation)
        self.assertTrue(bool(products.loc[1, "flag_category_missing"]))
        self.assertFalse(bool(products.loc[1, "flag_category_untranslated"]))
        self.assertTrue(bool(products.loc[2, "flag_category_untranslated"]))
        self.assertEqual(int(products["product_category_name_english"].isna().sum()), 2)
        self.assertEqual(len(products), 3)

    def test_zero_weight_does_not_block_volume_and_unknown_is_not_zero(self):
        products = self.clean()
        self.assertTrue(bool(products.loc[0, "flag_weight_zero"]))
        self.assertFalse(bool(products.loc[0, "can_use_weight"]))
        self.assertTrue(bool(products.loc[0, "can_calculate_volume"]))
        self.assertEqual(int(products.loc[0, "product_volume_cm3"]), 24)
        self.assertTrue(pd.isna(products.loc[1, "product_weight_g"]))
        self.assertTrue(pd.isna(products.loc[1, "flag_weight_zero"]))
        self.assertTrue(pd.isna(products.loc[1, "product_volume_cm3"]))
        raw = self.raw.copy()
        raw.loc[2, "product_length_cm"] = "0"
        products = self.clean(raw)
        self.assertFalse(bool(products.loc[2, "can_calculate_volume"]))
        self.assertTrue(bool(products.loc[2, "flag_dimensions_nonpositive"]))
        self.assertTrue(pd.isna(products.loc[2, "product_volume_cm3"]))

    def test_repeated_product_preserves_item_lines_and_money(self):
        items = clean_order_items(self.raw_items)
        original_items = items.copy(deep=True)
        joined = join_items_products(items, self.clean())
        assert_frame_equal(items, original_items)
        self.assertEqual(len(joined), 4)
        self.assertEqual(int(joined["product_id"].eq("P1").sum()), 2)
        self.assertEqual(int(joined["price_cents"].sum()), 3102)
        self.assertEqual(int(joined["freight_cents"].sum()), 210)
        self.assertTrue(reconcile_product_totals(items, joined)["差额"].eq(0).all())
        self.assertFalse(joined.duplicated(["order_id", "order_item_id"]).any())

    def test_translation_requires_nonempty_unique_key_not_unique_english(self):
        for bad in [
            pd.concat([self.translation, self.translation], ignore_index=True),
            self.translation.assign(product_category_name=None),
            self.translation.assign(product_category_name=" "),
            self.translation.assign(product_category_name_english=" "),
            self.translation.assign(product_category_name_english=None),
        ]:
            with self.subTest(values=bad.to_dict()), self.assertRaises(ValueError):
                self.clean(translation=bad)
        # 两个原始品类共用英文展示名，不会使每个原始键匹配多条记录。
        shared_name = pd.DataFrame({
            "product_category_name": ["cat_a", "cat_b"],
            "product_category_name_english": ["shared", "shared"],
        })
        self.assertEqual(len(self.clean(translation=shared_name)), 3)

    def test_invalid_numeric_stops_without_rounding_or_dropping_products(self):
        for value in ["abc", "inf", "-1", "1.5"]:
            raw = self.raw.copy()
            raw.loc[0, "product_length_cm"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.clean(raw)
        # 全部尺寸未知仍保留商品；无有效体积时统计量为 None。
        raw = self.raw.copy()
        raw[["product_length_cm", "product_height_cm", "product_width_cm"]] = None
        products = self.clean(raw)
        joined = join_items_products(clean_order_items(self.raw_items), products)
        metrics = summarize_product_metrics(products, self.translation, joined)
        self.assertEqual(len(products), 3)
        self.assertEqual(metrics["volume_eligible_products"], 0)
        self.assertIsNone(metrics["volume_mean_cm3"])
        self.assertIsNone(metrics["volume_max_cm3"])

    def test_invalid_keys_or_unmatched_item_stop_but_unused_master_is_allowed(self):
        items = clean_order_items(self.raw_items)
        products = self.clean()
        with self.assertRaises(ValueError):
            self.clean(pd.concat([self.raw, self.raw.iloc[[0]]], ignore_index=True))
        raw = self.raw.copy()
        raw.loc[0, "product_id"] = None
        with self.assertRaises(ValueError):
            self.clean(raw)
        with self.assertRaises(ValueError):
            join_items_products(pd.concat([items, items.iloc[[0]]], ignore_index=True), products)
        orphan = items.copy()
        orphan.loc[0, "product_id"] = "NOT_FOUND"
        with self.assertRaises(ValueError):
            join_items_products(orphan, products)
        extra = products.iloc[[0]].copy()
        extra["product_id"] = "UNUSED"
        joined = join_items_products(items, pd.concat([products, extra], ignore_index=True))
        self.assertEqual(len(joined), 4)

    def test_control_totals_reject_changed_money_and_duplicate_item(self):
        items = clean_order_items(self.raw_items)
        joined = join_items_products(items, self.clean())
        changed = joined.copy()
        changed.loc[0, "price_cents"] += 1
        with self.assertRaises(ValueError):
            reconcile_product_totals(items, changed)
        duplicate = pd.concat([joined, joined.iloc[[0]]], ignore_index=True)
        with self.assertRaises(ValueError):
            reconcile_product_totals(items, duplicate)


if __name__ == "__main__":
    unittest.main()
