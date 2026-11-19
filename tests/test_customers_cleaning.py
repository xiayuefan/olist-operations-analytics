"""客户阶段业务边界：ID 粒度、前导零、地区分组和数量守恒。"""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from customers_cleaning import (
    clean_customers, customer_field_changes, join_orders_customers,
    reconcile_customer_totals, summarize_city_orders,
)


class CustomerBusinessRules(unittest.TestCase):
    def setUp(self):
        self.raw = pd.DataFrame([
            ["C1", "U1", "01151", "agua branca", "AL"],
            ["C2", "U1", "09790", "agua branca", "PB"],
            ["C3", "U2", "08775", "sao paulo", "SP"],
        ], columns=[
            "customer_id", "customer_unique_id", "customer_zip_code_prefix",
            "customer_city", "customer_state",
        ])
        self.orders = pd.DataFrame({
            "order_id": ["O1", "O2", "O3"],
            "customer_id": ["C1", "C2", "C3"],
            "order_status": ["delivered", "canceled", "delivered"],
        })

    def flow(self, raw=None):
        cleaned = clean_customers(self.raw if raw is None else raw)
        joined = join_orders_customers(self.orders, cleaned)
        city_orders = summarize_city_orders(joined)
        return cleaned, joined, city_orders

    def test_repeated_unique_id_keeps_customer_records_and_order_links(self):
        original = self.raw.copy(deep=True)
        cleaned, joined, city_orders = self.flow()
        pd.testing.assert_frame_equal(self.raw, original)
        self.assertEqual(len(cleaned), 3)
        self.assertEqual(cleaned["customer_unique_id"].nunique(), 2)
        self.assertEqual(len(joined), 3)
        self.assertTrue(joined["customers_match"].eq("both").all())
        self.assertTrue(reconcile_customer_totals(
            self.orders, cleaned, joined, city_orders)["差额"].eq(0).all())

    def test_postcode_leading_zero_is_kept_and_bad_postcodes_are_not_guessed(self):
        raw = self.raw.copy()
        raw.loc[1, "customer_zip_code_prefix"] = "1151"
        raw.loc[2, "customer_zip_code_prefix"] = None
        cleaned, joined, city_orders = self.flow(raw)
        self.assertEqual(cleaned.loc[0, "customer_zip_code_prefix"], "01151")
        self.assertEqual(cleaned.loc[1, "customer_zip_code_prefix"], "1151")
        self.assertTrue(bool(cleaned.loc[1, "flag_zip_format_invalid"]))
        self.assertTrue(bool(cleaned.loc[2, "flag_zip_format_invalid"]))
        # 州城市分组不依赖邮编；不能因邮编异常就丢掉这两笔订单。
        self.assertEqual(int(city_orders["order_count"].sum()), 3)
        self.assertEqual(len(joined), 3)

    def test_case_normalization_is_auditable_and_unknown_state_is_flagged(self):
        raw = self.raw.copy()
        raw.loc[1, "customer_state"] = " pb "
        raw.loc[1, "customer_city"] = " AGUA BRANCA "
        raw.loc[1, "customer_zip_code_prefix"] = " 09790 "
        raw.loc[2, "customer_state"] = "AA"
        cleaned, joined, city_orders = self.flow(raw)
        self.assertEqual(cleaned.loc[1, "customer_state"], "PB")
        self.assertEqual(cleaned.loc[1, "customer_city"], "agua branca")
        self.assertEqual(len(customer_field_changes(raw, cleaned)), 3)
        self.assertFalse(bool(cleaned.loc[2, "flag_state_format_invalid"]))
        self.assertTrue(bool(cleaned.loc[2, "flag_state_unknown"]))
        self.assertEqual(len(joined), 3)
        self.assertEqual(int(city_orders["order_count"].sum()), 2)

    def test_same_city_name_in_two_states_stays_in_two_groups(self):
        cleaned, joined, city_orders = self.flow()
        same_name = city_orders.loc[city_orders["customer_city"].eq("agua branca")]
        self.assertEqual(set(same_name["customer_state"]), {"AL", "PB"})
        self.assertEqual(len(same_name), 2)
        self.assertEqual(int(same_name["order_count"].sum()), 2)

    def test_all_unusable_locations_leave_orders_intact_and_no_city_counts(self):
        raw = self.raw.copy()
        raw["customer_state"] = "AA"
        cleaned, joined, city_orders = self.flow(raw)
        self.assertEqual(len(joined), 3)
        self.assertEqual(int(cleaned["flag_state_unknown"].sum()), 3)
        self.assertTrue(city_orders.empty)
        self.assertTrue(reconcile_customer_totals(
            self.orders, cleaned, joined, city_orders)["差额"].eq(0).all())

    def test_duplicate_or_blank_keys_and_unmatched_order_keys_stop(self):
        for col, value in [("customer_id", None), ("customer_id", " "),
                           ("customer_unique_id", None), ("customer_id", " C1 ")]:
            with self.subTest(col=col, value=value):
                raw = self.raw.copy()
                raw.loc[0, col] = value
                with self.assertRaises(ValueError):
                    clean_customers(raw)
        with self.assertRaises(ValueError):
            clean_customers(pd.concat([self.raw, self.raw.iloc[[0]]], ignore_index=True))
        orders = self.orders.copy()
        orders.loc[0, "customer_id"] = "UNKNOWN"
        with self.assertRaises(ValueError):
            join_orders_customers(orders, clean_customers(self.raw))

    def test_unused_customer_records_do_not_break_matched_customer_controls(self):
        extra = pd.DataFrame([["C4", "U3", "01000", "sao paulo", "SP"]], columns=self.raw.columns)
        cleaned, joined, city_orders = self.flow(pd.concat([self.raw, extra], ignore_index=True))
        self.assertEqual(len(cleaned), 4)
        self.assertEqual(len(joined), 3)
        self.assertTrue(reconcile_customer_totals(
            self.orders, cleaned, joined, city_orders)["差额"].eq(0).all())
        changed = city_orders.copy()
        changed.loc[0, "order_count"] += 1
        with self.assertRaises(ValueError):
            reconcile_customer_totals(self.orders, cleaned, joined, changed)


if __name__ == "__main__":
    unittest.main()
