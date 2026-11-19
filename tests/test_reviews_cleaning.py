"""评价规则回归检查：保护粒度、取值规则、缺失状态与明细保留。"""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from reviews_cleaning import (
    aggregate_order_reviews, clean_order_reviews, compare_review_rules,
    join_orders_reviews, reconcile_review_totals, select_latest_reviews,
)


class ReviewBusinessRules(unittest.TestCase):
    def setUp(self):
        self.raw = pd.DataFrame([
            ["R1", "A", "2", None, "   ", "2017-07-31 00:00:00", "2017-08-01 20:39:04"],
            ["R2", "A", "5", "标题", "满意", "2017-08-03 00:00:00", "2017-08-04 09:32:59"],
            # 同一 review_id 出现在另一订单是允许的，组合键仍唯一。
            ["R1", "B", "1", " ", None, "2017-08-01 00:00:00", "2017-08-02 10:00:00"],
        ], columns=[
            "review_id", "order_id", "review_score", "review_comment_title",
            "review_comment_message", "review_creation_date", "review_answer_timestamp",
        ])
        self.orders = pd.DataFrame({
            "order_id": ["A", "B", "C"], "order_status": ["delivered", "delivered", "shipped"],
        })

    def flow(self, raw=None):
        cleaned = clean_order_reviews(self.raw if raw is None else raw)
        latest = select_latest_reviews(cleaned)
        summary = aggregate_order_reviews(cleaned, latest)
        joined = join_orders_reviews(self.orders, summary)
        return cleaned, latest, summary, joined

    def test_multireview_rules_keep_detail_and_missing_orders_unknown(self):
        original = self.raw.copy(deep=True)
        cleaned, latest, summary, joined = self.flow()
        pd.testing.assert_frame_equal(self.raw, original)
        self.assertEqual(len(cleaned), 3)
        self.assertEqual(len(latest), 2)
        a = summary.set_index("order_id").loc["A"]
        self.assertEqual(int(a["review_record_count"]), 2)
        self.assertEqual(int(a["low_score_record_count"]), 1)
        self.assertEqual(int(a["latest_review_score"]), 5)
        self.assertTrue(bool(a["any_low_score"]))
        self.assertFalse(bool(a["latest_is_low_score"]))
        self.assertTrue(bool(a["rules_disagree"]))
        missing = joined.set_index("order_id").loc["C"]
        for col in ["latest_review_score", "latest_is_low_score", "any_low_score", "rules_disagree"]:
            self.assertTrue(pd.isna(missing[col]))
        self.assertTrue(reconcile_review_totals(cleaned, latest, summary, joined)[
            ["汇总差额", "关联差额"]].eq(0).all().all())
        self.assertEqual(int(compare_review_rules(summary).loc["任意一次低评分", "低评分订单数"]), 2)

    def test_missing_text_creation_date_and_long_lag_do_not_remove_valid_scores(self):
        raw = self.raw.copy()
        raw.loc[0, "review_creation_date"] = "2015-01-01 00:00:00"
        raw.loc[1, "review_creation_date"] = None
        cleaned, latest, summary, joined = self.flow(raw)
        self.assertEqual(len(cleaned), len(raw))
        self.assertFalse(bool(cleaned.loc[0, "has_comment_message"]))
        self.assertTrue(bool(cleaned.loc[0, "is_low_score"]))
        self.assertGreater(float(cleaned.loc[0, "review_answer_lag_days"]), 365)
        self.assertTrue(pd.isna(cleaned.loc[1, "review_answer_lag_days"]))
        self.assertTrue(bool(cleaned.loc[1, "flag_missing_creation_date"]))
        self.assertEqual(int(summary.set_index("order_id").loc["A", "latest_review_score"]), 5)

    def test_invalid_scores_dates_and_duplicate_pairs_stop(self):
        for col, value in [
            ("review_score", None), ("review_score", "0"), ("review_score", "6"),
            ("review_score", "2.5"), ("review_answer_timestamp", "bad-date"),
            ("order_id", " "), ("review_id", None),
        ]:
            with self.subTest(col=col, value=value):
                raw = self.raw.copy()
                raw.loc[0, col] = value
                with self.assertRaises(ValueError):
                    clean_order_reviews(raw)
        raw = pd.concat([self.raw, self.raw.iloc[[0]]], ignore_index=True)
        with self.assertRaises(ValueError):
            clean_order_reviews(raw)

    def test_tied_latest_times_require_a_rule(self):
        raw = self.raw.copy()
        raw.loc[1, "review_creation_date"] = raw.loc[0, "review_creation_date"]
        raw.loc[1, "review_answer_timestamp"] = raw.loc[0, "review_answer_timestamp"]
        with self.assertRaisesRegex(ValueError, "并列"):
            select_latest_reviews(clean_order_reviews(raw))

    def test_missing_or_reversed_submission_time_is_not_guessed(self):
        for answer in [None, "2017-07-01 12:00:00"]:
            with self.subTest(answer=answer):
                raw = self.raw.copy()
                raw.loc[0, "review_answer_timestamp"] = answer
                cleaned = clean_order_reviews(raw)
                self.assertEqual(len(cleaned), 3)
                self.assertTrue(pd.isna(cleaned.loc[0, "review_answer_lag_days"]))
                with self.assertRaises(ValueError):
                    select_latest_reviews(cleaned)

    def test_passing_an_old_review_as_latest_is_detected(self):
        cleaned = clean_order_reviews(self.raw)
        wrong_latest = cleaned.iloc[[0, 2]].copy()
        with self.assertRaisesRegex(ValueError, "最大提交时间"):
            aggregate_order_reviews(cleaned, wrong_latest)

    def test_orphan_orders_and_changed_control_totals_stop(self):
        cleaned, latest, summary, joined = self.flow()
        orphan = summary.copy()
        orphan.loc[0, "order_id"] = "ORPHAN"
        with self.assertRaises(ValueError):
            join_orders_reviews(self.orders, orphan)
        changed = joined.copy()
        changed.loc[changed["order_id"].eq("A"), "low_score_record_count"] = 0
        with self.assertRaises(ValueError):
            reconcile_review_totals(cleaned, latest, summary, changed)


if __name__ == "__main__":
    unittest.main()
