USE olist_operations_analytics;

-- Q21 为每个州、每种延迟状态的低评分率计算 Wilson 95% 置信区间。
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
group_counts AS (
    -- 这次让延迟组和按时或提前组各占一行，用同一套公式计算区间。
    SELECT o.customer_state,
           o.is_late,
           COUNT(r.latest_review_score) AS rated_orders,
           COUNT(CASE WHEN r.latest_review_score IN (1, 2) THEN 1 END) AS low_score_orders
    FROM eligible_orders AS o
    LEFT JOIN latest_order_reviews AS r ON o.order_id = r.order_id
    GROUP BY o.customer_state, o.is_late
),
group_rates AS (
    -- 分母为 0 时，比率和区间都返回 NULL。z 为双侧 95% 区间使用的临界值。
    SELECT group_counts.*,
           NULLIF(rated_orders, 0) AS n,
           1.0E0 * low_score_orders / NULLIF(rated_orders, 0) AS p,
           1.959963984540054E0 AS z
    FROM group_counts
),
wilson_terms AS (
    SELECT group_rates.*,
           1 + POWER(z, 2) / n AS denominator,
           p + POWER(z, 2) / (2 * n) AS midpoint_term,
           z * SQRT((p * (1 - p) + POWER(z, 2) / (4 * n)) / n) AS margin_term
    FROM group_rates
)
SELECT customer_state,
       CASE WHEN is_late = 1 THEN 'late' ELSE 'on_time_or_early' END AS delivery_group,
       rated_orders,
       low_score_orders,
       ROUND(100 * p, 2) AS low_score_rate_pct,
       ROUND(100 * GREATEST(0, (midpoint_term - margin_term) / denominator), 2) AS ci_lower_pct,
       ROUND(100 * LEAST(1, (midpoint_term + margin_term) / denominator), 2) AS ci_upper_pct
FROM wilson_terms
ORDER BY customer_state, is_late;
