"""支付指标的业务边界回归检查；使用标准库 unittest。"""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from items_cleaning import aggregate_order_items, clean_order_items
from payments_cleaning import (
    SUMMARY_FLAG_COLS, aggregate_order_payments, clean_order_payments,
    join_orders_payments, reconcile_order_amounts, reconcile_payment_totals,
    recheck_raw_order, summarize_payment_metrics,
)


class PaymentBusinessRules(unittest.TestCase):
    def setUp(self):
        self.orders = pd.DataFrame({
            "order_id": ["A", "B", "C"], "order_status": ["delivered"] * 3,
        })
        self.raw = pd.DataFrame([
            ["A", "1", "voucher", "1", "0.00"],
            ["A", "2", "credit_card", "0", "10.00"],
            ["C", "1", "not_defined", "1", "0.00"],
        ], columns=["order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value"])
        self.items = pd.DataFrame([
            ["A", "1", "P1", "S1", "2018-01-10 12:00:00", "8.00", "2.00"],
            ["B", "1", "P2", "S1", "2018-01-10 12:00:00", "2.00", "0.50"],
        ], columns=["order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price", "freight_value"])

    def flow(self, raw=None, items=None):
        cleaned = clean_order_payments(self.raw if raw is None else raw)
        summary = aggregate_order_payments(cleaned)
        joined = join_orders_payments(self.orders, summary)
        item_summary = aggregate_order_items(clean_order_items(self.items if items is None else items))
        amounts = reconcile_order_amounts(joined, item_summary)
        return cleaned, summary, joined, amounts

    def test_split_payment_zero_record_and_unknown_order_are_distinct(self):
        original = self.raw.copy(deep=True)
        cleaned, summary, joined, amounts = self.flow()
        pd.testing.assert_frame_equal(self.raw, original)
        summary = summary.set_index("order_id")
        self.assertTrue(bool(summary.loc["A", "has_zero_payment_record"]))
        self.assertEqual(int(summary.loc["A", "payment_amount_cents"]), 1000)
        self.assertEqual(int(summary.loc["C", "payment_amount_cents"]), 0)
        indexed = joined.set_index("order_id")
        self.assertTrue(pd.isna(indexed.loc["B", "payment_amount_cents"]))
        for col in SUMMARY_FLAG_COLS:
            self.assertTrue(pd.isna(indexed.loc["B", col]))
        states = amounts.set_index("order_id")
        self.assertEqual(states.loc["A", "amount_reconcile_status"], "金额完全一致")
        for order_id in ["B", "C"]:
            self.assertTrue(pd.isna(states.loc[order_id, "payment_difference_cents"]))
            self.assertTrue(pd.isna(states.loc[order_id, "flag_amount_mismatch"]))
            self.assertEqual(states.loc[order_id, "amount_reconcile_status"], "无法核对")
        self.assertTrue(reconcile_payment_totals(cleaned, summary.reset_index(), joined)[
            ["汇总差额", "关联差额"]].eq(0).all().all())

    def test_one_cent_difference_is_preserved_and_raw_recheck_is_independent(self):
        raw = self.raw.copy()
        raw.loc[1, "payment_value"] = "10.01"
        cleaned, summary, joined, amounts = self.flow(raw=raw)
        metrics = summarize_payment_metrics(cleaned, summary, amounts)
        self.assertEqual(metrics["amount_mismatch_orders"], 1)
        self.assertEqual(metrics["abs_difference_1_cent"], 1)
        case = recheck_raw_order(self.items, raw, amounts, "A")
        self.assertEqual(int(case.loc["金额差额（分）", "原始明细重算"]), 1)
        self.assertTrue(case["差值"].eq(0).all())
        corrupted = amounts.copy()
        corrupted.loc[corrupted["order_id"].eq("A"), "payment_amount_cents"] = 999
        with self.assertRaises(ValueError):
            recheck_raw_order(self.items, raw, corrupted, "A")

    def test_zero_installments_stay_flagged_without_changing_payment(self):
        cleaned, summary, joined, amounts = self.flow()
        self.assertEqual(int(cleaned.loc[1, "payment_installments"]), 0)
        self.assertTrue(bool(cleaned.loc[1, "flag_zero_installments"]))
        self.assertEqual(int(cleaned.loc[1, "payment_value_cents"]), 1000)
        self.assertEqual(summarize_payment_metrics(cleaned, summary, amounts)["zero_installment_rows"], 1)

    def test_no_comparable_orders_returns_unknown_totals(self):
        cleaned, summary, joined, amounts = self.flow(items=self.items.loc[self.items["order_id"].eq("B")])
        metrics = summarize_payment_metrics(cleaned, summary, amounts)
        self.assertEqual(metrics["amount_comparable_orders"], 0)
        for field in ["comparable_payment_cents", "comparable_items_cents", "signed_difference_cents",
                      "absolute_difference_cents", "max_abs_difference_cents"]:
            self.assertIsNone(metrics[field])

    def test_invalid_values_and_normalized_key_collisions_stop(self):
        for col, value in [
            ("payment_value", None), ("payment_value", "-1.00"),
            ("payment_value", "0.001"), ("payment_value", "Infinity"),
            ("payment_sequential", "0"), ("payment_sequential", "1.5"),
            ("payment_installments", "-1"), ("payment_installments", "1.5"),
            ("payment_installments", None), ("payment_type", "unknown_method"),
        ]:
            with self.subTest(col=col, value=value):
                raw = self.raw.copy()
                raw.loc[0, col] = value
                with self.assertRaises(ValueError):
                    clean_order_payments(raw)
        raw = self.raw.copy()
        raw.loc[1, "payment_sequential"] = "01"
        with self.assertRaises(ValueError):
            clean_order_payments(raw)

    def test_orphans_and_control_total_changes_stop(self):
        cleaned = clean_order_payments(self.raw)
        summary = aggregate_order_payments(cleaned)
        orphan = summary.copy()
        orphan.loc[0, "order_id"] = "ORPHAN"
        with self.assertRaises(ValueError):
            join_orders_payments(self.orders, orphan)
        joined = join_orders_payments(self.orders, summary)
        joined.loc[joined["order_id"].eq("A"), "payment_amount_cents"] = 999
        with self.assertRaises(ValueError):
            reconcile_payment_totals(cleaned, summary, joined)


if __name__ == "__main__":
    unittest.main()
