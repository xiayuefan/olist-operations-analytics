USE olist_operations_analytics;

-- Q20 在同一个客户州内比较延迟订单与按时或提前订单的低评分率。
WITH eligible_orders AS (
    SELECT o.order_id, c.customer_state, o.delivery_delay_days > 0 AS is_late
    FROM orders AS o
    JOIN customers AS c ON o.customer_id = c.customer_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-09-01'
      AND o.is_valid_delay = 1
      AND o.delivery_delay_days IS NOT NULL
),
latest_review_times AS (
    -- 沿用 Q19 的最新评分口径。提交时间无法确认的订单留待核查。
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
state_counts AS (
    -- 左关联保留各州。COUNT 只数满足条件且有有效评分的订单。
    SELECT o.customer_state,
           COUNT(CASE WHEN o.is_late = 0 THEN r.latest_review_score END) AS on_time_rated_orders,
           COUNT(CASE WHEN o.is_late = 1 THEN r.latest_review_score END) AS late_rated_orders,
           COUNT(CASE WHEN o.is_late = 0 AND r.latest_review_score IN (1, 2) THEN 1 END) AS on_time_low_score_orders,
           COUNT(CASE WHEN o.is_late = 1 AND r.latest_review_score IN (1, 2) THEN 1 END) AS late_low_score_orders
    FROM eligible_orders AS o
    LEFT JOIN latest_order_reviews AS r ON o.order_id = r.order_id
    GROUP BY o.customer_state
),
state_rates AS (
    -- 先保留多位小数算差值，再四舍五入展示。
    SELECT state_counts.*,
           100.000000 * on_time_low_score_orders / NULLIF(on_time_rated_orders, 0) AS on_time_pct,
           100.000000 * late_low_score_orders / NULLIF(late_rated_orders, 0) AS late_pct
    FROM state_counts
)
SELECT customer_state,
       on_time_rated_orders,
       late_rated_orders,
       on_time_low_score_orders,
       late_low_score_orders,
       ROUND(on_time_pct, 2) AS on_time_low_score_pct,
       ROUND(late_pct, 2) AS late_low_score_pct,
       ROUND(late_pct - on_time_pct, 2) AS low_score_gap_pp
FROM state_rates
ORDER BY on_time_rated_orders + late_rated_orders DESC, customer_state;
