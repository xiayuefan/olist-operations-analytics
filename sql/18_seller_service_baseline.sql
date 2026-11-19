USE olist_operations_analytics;

-- Q25 核对已交付订单中有多少笔可归入单一卖家。
WITH order_seller_counts AS (
    SELECT order_id, COUNT(DISTINCT seller_id) AS seller_count
    FROM order_items
    GROUP BY order_id
)
SELECT COUNT(*) AS delivered_orders,
       COUNT(CASE WHEN s.seller_count = 1 THEN 1 END) AS single_seller_orders,
       COUNT(CASE WHEN s.seller_count > 1 THEN 1 END) AS multi_seller_orders,
       COUNT(CASE WHEN s.order_id IS NULL THEN 1 END) AS orders_without_items
FROM orders AS o
LEFT JOIN order_seller_counts AS s ON o.order_id = s.order_id
WHERE o.order_status = 'delivered'
  AND o.order_purchase_timestamp >= '2017-01-01'
  AND o.order_purchase_timestamp <  '2018-09-01';

-- Q26 按卖家汇总单卖家订单，比较订单量、延迟率与低评分率。
WITH single_order_sellers AS (
    -- 多条商品明细可以来自同一卖家。先保证只有一个不同的卖家 ID，再取这个 ID。
    SELECT order_id, MIN(seller_id) AS seller_id
    FROM order_items
    GROUP BY order_id
    HAVING COUNT(DISTINCT seller_id) = 1
),
latest_review_times AS (
    -- 沿用 Q19 的最新有效评分规则。
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
    -- 评分缺失的订单仍保留，可以独立参加延迟指标的计算。
    LEFT JOIN latest_order_reviews AS r ON o.order_id = r.order_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-09-01'
    GROUP BY s.seller_id
)
SELECT seller_id,
       single_seller_orders,
       valid_delay_orders,
       late_orders,
       ROUND(100.0 * late_orders / NULLIF(valid_delay_orders, 0), 2) AS late_rate_pct,
       rated_orders,
       low_score_orders,
       ROUND(100.0 * low_score_orders / NULLIF(rated_orders, 0), 2) AS low_score_rate_pct
FROM seller_counts
ORDER BY single_seller_orders DESC, seller_id
LIMIT 10;
