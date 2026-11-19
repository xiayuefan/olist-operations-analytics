USE olist_operations_analytics;

-- Q27 用全体单卖家订单作基线，筛选延迟率和低评分率都高于基线的卖家。
WITH single_order_sellers AS (
    SELECT order_id, MIN(seller_id) AS seller_id
    FROM order_items
    GROUP BY order_id
    HAVING COUNT(DISTINCT seller_id) = 1
),
latest_review_times AS (
    -- 沿用 Q26 的最新有效评分规则。
    SELECT order_id, MAX(review_answer_timestamp) AS latest_answer_at
    FROM order_reviews
    GROUP BY order_id
    HAVING COUNT(review_answer_timestamp) = COUNT(*)
       AND MAX(flag_answer_before_creation) = 0
),
latest_order_reviews AS (
    SELECT r.order_id, MAX(r.review_score) AS latest_review_score
    FROM order_reviews AS r
    JOIN latest_review_times AS t ON r.order_id = t.order_id
                                 AND r.review_answer_timestamp = t.latest_answer_at
    GROUP BY r.order_id
    HAVING COUNT(*) = 1
),
seller_counts AS (
    SELECT s.seller_id,
           COUNT(*) AS single_seller_orders,
           COUNT(CASE WHEN o.is_valid_delay = 1 THEN o.delivery_delay_days END) AS valid_delay_orders,
           COUNT(CASE WHEN o.is_valid_delay = 1 AND o.delivery_delay_days > 0 THEN 1 END) AS late_orders,
           COUNT(r.latest_review_score) AS rated_orders,
           COUNT(CASE WHEN r.latest_review_score IN (1, 2) THEN 1 END) AS low_score_orders
    FROM orders AS o
    JOIN single_order_sellers AS s ON o.order_id = s.order_id
    LEFT JOIN latest_order_reviews AS r ON o.order_id = r.order_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-09-01'
    GROUP BY s.seller_id
),
with_baseline AS (
    -- 先加总订单数，再计算整体比率。此处覆盖所有卖家，样本门槛在下一层使用。
    SELECT seller_counts.*,
           SUM(late_orders) OVER () AS total_late_orders,
           SUM(valid_delay_orders) OVER () AS total_valid_delay_orders,
           SUM(low_score_orders) OVER () AS total_low_score_orders,
           SUM(rated_orders) OVER () AS total_rated_orders
    FROM seller_counts
),
candidates AS (
    SELECT *
    FROM with_baseline
    WHERE valid_delay_orders >= 50 AND rated_orders >= 50
      -- 交叉相乘等价于比较原始比率，避免四舍五入影响是否入选。
      AND late_orders * total_valid_delay_orders > total_late_orders * valid_delay_orders
      AND low_score_orders * total_rated_orders > total_low_score_orders * rated_orders
)
SELECT seller_id,
       single_seller_orders,
       valid_delay_orders,
       late_orders,
       ROUND(100.0 * late_orders / valid_delay_orders, 2) AS late_rate_pct,
       ROUND(100.0 * total_late_orders / total_valid_delay_orders, 2) AS baseline_late_rate_pct,
       rated_orders,
       low_score_orders,
       ROUND(100.0 * low_score_orders / rated_orders, 2) AS low_score_rate_pct,
       ROUND(100.0 * total_low_score_orders / total_rated_orders, 2) AS baseline_low_score_rate_pct,
       COUNT(*) OVER () AS candidate_sellers
FROM candidates
-- 先看低评分涉及的订单数，低评分笔数相同再比较延迟笔数。
ORDER BY low_score_orders DESC, late_orders DESC, seller_id
LIMIT 10;
