USE olist_operations_analytics;

-- Q22 对两组使用同一套客户州权重，再比较整体低评分率。
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
    -- 沿用 Q20 的最新有效评分规则。
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
    -- 本课只比较有有效评分的订单，两组分别计数。
    SELECT o.customer_state,
           COUNT(CASE WHEN o.is_late = 0 THEN 1 END) AS on_time_rated_orders,
           COUNT(CASE WHEN o.is_late = 1 THEN 1 END) AS late_rated_orders,
           COUNT(CASE WHEN o.is_late = 0 AND r.latest_review_score IN (1, 2) THEN 1 END) AS on_time_low_score_orders,
           COUNT(CASE WHEN o.is_late = 1 AND r.latest_review_score IN (1, 2) THEN 1 END) AS late_low_score_orders
    FROM eligible_orders AS o
    JOIN latest_order_reviews AS r ON o.order_id = r.order_id
    GROUP BY o.customer_state
),
comparable_states AS (
    -- 州内两组都需要有可估计的低评分率。两种整体口径使用相同的州。
    SELECT state_counts.*,
           on_time_rated_orders + late_rated_orders AS state_rated_orders,
           1.0000000000 * on_time_low_score_orders / on_time_rated_orders AS on_time_rate,
           1.0000000000 * late_low_score_orders / late_rated_orders AS late_rate
    FROM state_counts
    WHERE on_time_rated_orders > 0 AND late_rated_orders > 0
),
overall_rates AS (
    SELECT COUNT(*) AS states_included,
           COALESCE(SUM(state_rated_orders), 0) AS rated_orders,
           (SELECT SUM(on_time_rated_orders + late_rated_orders) FROM state_counts) AS all_rated_orders,
           100.0000000000 * SUM(on_time_low_score_orders) / NULLIF(SUM(on_time_rated_orders), 0) AS observed_on_time_pct,
           100.0000000000 * SUM(late_low_score_orders) / NULLIF(SUM(late_rated_orders), 0) AS observed_late_pct,
           -- 各州权重等于该州两组有效评分订单之和占全部纳入订单的比例。
           100 * SUM(state_rated_orders * on_time_rate) / NULLIF(SUM(state_rated_orders), 0) AS standardized_on_time_pct,
           100 * SUM(state_rated_orders * late_rate) / NULLIF(SUM(state_rated_orders), 0) AS standardized_late_pct
    FROM comparable_states
),
comparison AS (
    SELECT 1 AS method_order, 'observed' AS comparison_method, states_included, rated_orders,
           COALESCE(all_rated_orders, 0) - rated_orders AS excluded_rated_orders,
           observed_on_time_pct AS on_time_pct, observed_late_pct AS late_pct
    FROM overall_rates
    UNION ALL
    SELECT 2, 'state_standardized', states_included, rated_orders,
           COALESCE(all_rated_orders, 0) - rated_orders,
           standardized_on_time_pct, standardized_late_pct
    FROM overall_rates
)
SELECT comparison_method,
       states_included,
       rated_orders,
       excluded_rated_orders,
       ROUND(on_time_pct, 2) AS on_time_low_score_pct,
       ROUND(late_pct, 2) AS late_low_score_pct,
       ROUND(late_pct - on_time_pct, 2) AS low_score_gap_pp
FROM comparison
ORDER BY method_order;
