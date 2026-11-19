USE olist_operations_analytics;

-- Q28 比较只纳入单卖家订单和纳入全部关联订单时的卖家指标。
WITH order_seller_pairs AS (
    -- 同一订单、同一卖家的多条商品明细只保留一对关系。
    SELECT DISTINCT order_id, seller_id
    FROM order_items
),
seller_links AS (
    SELECT order_id, seller_id,
           COUNT(*) OVER (PARTITION BY order_id) AS seller_count
    FROM order_seller_pairs
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
seller_order_metrics AS (
    SELECT s.seller_id, s.seller_count,
           CASE WHEN o.is_valid_delay = 1 THEN o.delivery_delay_days END AS delay_days,
           r.latest_review_score
    FROM orders AS o
    JOIN seller_links AS s ON o.order_id = s.order_id
    LEFT JOIN latest_order_reviews AS r ON o.order_id = r.order_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-09-01'
),
top_sellers AS (
    -- 两种口径展示同一批卖家，按全部关联订单数选出前五位。
    SELECT seller_id, COUNT(*) AS all_related_orders
    FROM seller_order_metrics
    GROUP BY seller_id
    ORDER BY all_related_orders DESC, seller_id
    LIMIT 5
),
scopes AS (
    SELECT 1 AS scope_order, 'single_seller_only' AS order_scope
    UNION ALL
    SELECT 2, 'all_related'
),
seller_scope_counts AS (
    SELECT t.seller_id, t.all_related_orders, s.scope_order, s.order_scope,
           COUNT(m.seller_id) AS related_orders,
           COUNT(m.delay_days) AS valid_delay_orders,
           COUNT(CASE WHEN m.delay_days > 0 THEN 1 END) AS late_orders,
           COUNT(m.latest_review_score) AS rated_orders,
           COUNT(CASE WHEN m.latest_review_score IN (1, 2) THEN 1 END) AS low_score_orders
    FROM top_sellers AS t
    CROSS JOIN scopes AS s
    -- 保留两种口径的行，即使某位卖家没有单卖家订单。
    LEFT JOIN seller_order_metrics AS m
        ON t.seller_id = m.seller_id AND (s.scope_order = 2 OR m.seller_count = 1)
    GROUP BY t.seller_id, t.all_related_orders, s.scope_order, s.order_scope
)
SELECT seller_id,
       order_scope,
       related_orders,
       valid_delay_orders,
       late_orders,
       ROUND(100.0 * late_orders / NULLIF(valid_delay_orders, 0), 2) AS late_rate_pct,
       rated_orders,
       low_score_orders,
       ROUND(100.0 * low_score_orders / NULLIF(rated_orders, 0), 2) AS low_score_rate_pct
FROM seller_scope_counts
ORDER BY all_related_orders DESC, seller_id, scope_order;
