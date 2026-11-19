USE olist_operations_analytics;

-- Q32 哪个履约阶段的长尾最明显？各阶段独立排除无效时间，按 k*(n-1) 线性插值。
WITH delivered AS (
    SELECT order_purchase_timestamp, order_approved_at, order_delivered_carrier_date, transit_days
    FROM orders
    WHERE order_status = 'delivered'
      AND order_purchase_timestamp >= '2017-01-01' AND order_purchase_timestamp < '2018-09-01'
), stage_samples AS (
    SELECT 1 AS stage_order, TIMESTAMPDIFF(SECOND, order_purchase_timestamp, order_approved_at) / 86400.0 AS days
    FROM delivered WHERE order_approved_at >= order_purchase_timestamp
    UNION ALL
    SELECT 2, TIMESTAMPDIFF(SECOND, order_approved_at, order_delivered_carrier_date) / 86400.0
    FROM delivered WHERE order_approved_at >= order_purchase_timestamp
                     AND order_delivered_carrier_date >= order_approved_at
    UNION ALL
    SELECT 3, transit_days FROM delivered WHERE transit_days IS NOT NULL
), ranked AS (
    SELECT stage_order, days, ROW_NUMBER() OVER (PARTITION BY stage_order ORDER BY days) AS rn,
           COUNT(*) OVER (PARTITION BY stage_order) AS n
    FROM stage_samples
), positions AS (
    SELECT ranked.*, 1 + 0.5 * (n - 1) AS p50_pos, 1 + 0.9 * (n - 1) AS p90_pos FROM ranked
)
SELECT CASE stage_order WHEN 1 THEN 'approval' WHEN 2 THEN 'handoff' ELSE 'transit' END AS stage,
       MAX(n) AS eligible_orders,
       ROUND(MAX(CASE WHEN rn = FLOOR(p50_pos) THEN days * (1 - p50_pos + FLOOR(p50_pos)) END)
           + MAX(CASE WHEN rn = CEIL(p50_pos) THEN days * (p50_pos - FLOOR(p50_pos)) END), 2) AS p50_days,
       ROUND(MAX(CASE WHEN rn = FLOOR(p90_pos) THEN days * (1 - p90_pos + FLOOR(p90_pos)) END)
           + MAX(CASE WHEN rn = CEIL(p90_pos) THEN days * (p90_pos - FLOOR(p90_pos)) END), 2) AS p90_days
FROM positions GROUP BY stage_order ORDER BY stage_order;

-- Q33 完整评分分布：可判断延迟不是资格条件。未能确定唯一最新评分的订单单列。
WITH latest_time AS (
    SELECT order_id, MAX(review_answer_timestamp) AS latest_at
    FROM order_reviews GROUP BY order_id
    HAVING COUNT(review_answer_timestamp) = COUNT(*) AND MAX(flag_answer_before_creation) = 0
), latest AS (
    SELECT r.order_id, MAX(r.review_score) AS score
    FROM order_reviews AS r
    JOIN latest_time AS t ON r.order_id = t.order_id AND r.review_answer_timestamp = t.latest_at
    GROUP BY r.order_id HAVING COUNT(*) = 1
), rating_counts AS (
    SELECT l.score, COUNT(*) AS delivered_orders
    FROM orders AS o LEFT JOIN latest AS l ON o.order_id = l.order_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= '2017-01-01' AND o.order_purchase_timestamp < '2018-09-01'
    GROUP BY l.score
)
SELECT score, delivered_orders,
       CASE WHEN score IS NOT NULL THEN ROUND(100.0 * delivered_orders /
            NULLIF(SUM(CASE WHEN score IS NOT NULL THEN delivered_orders ELSE 0 END) OVER (), 0), 2) END AS rated_share_pct
FROM rating_counts ORDER BY score IS NULL, score;

-- Q34 各客户州的运费负担。对各州先加总整数分，再除以同州商品成交额。
SELECT c.customer_state, SUM(i.price_cents) AS goods_cents, SUM(i.freight_cents) AS freight_cents,
       ROUND(100.0 * SUM(i.freight_cents) / NULLIF(SUM(i.price_cents), 0), 2) AS freight_over_goods_pct,
       COUNT(DISTINCT i.order_id) AS priced_orders
FROM order_items AS i
JOIN orders AS o ON i.order_id = o.order_id
JOIN customers AS c ON o.customer_id = c.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_purchase_timestamp >= '2017-01-01' AND o.order_purchase_timestamp < '2018-09-01'
GROUP BY c.customer_state ORDER BY freight_over_goods_pct DESC, c.customer_state;

-- Q35 入库后按订单复核原阶段的跨表支付对账。范围为全部历史、全部状态。
WITH item_amount AS (
    SELECT order_id, SUM(price_cents + freight_cents) AS goods_plus_freight_cents
    FROM order_items GROUP BY order_id
), payment_amount AS (
    SELECT order_id, SUM(payment_value_cents) AS paid_cents
    FROM order_payments GROUP BY order_id
), order_diff AS (
    SELECT p.paid_cents - i.goods_plus_freight_cents AS difference_cents
    FROM orders AS o
    LEFT JOIN item_amount AS i ON o.order_id = i.order_id
    LEFT JOIN payment_amount AS p ON o.order_id = p.order_id
)
SELECT CASE WHEN difference_cents IS NULL THEN 'cannot_compare'
            WHEN difference_cents = 0 THEN 'matched'
            WHEN difference_cents > 0 THEN 'payment_greater'
            ELSE 'payment_smaller' END AS comparison,
       COUNT(*) AS orders_in_group,
       SUM(difference_cents) AS net_difference_cents
FROM order_diff GROUP BY comparison ORDER BY comparison;
