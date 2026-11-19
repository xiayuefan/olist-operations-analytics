USE olist_operations_analytics;

-- Q01 订单状态分布。orders 已经一行一单，直接 COUNT(*)。
SELECT order_status,
       COUNT(*) AS order_count,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM orders), 2) AS order_share_pct
FROM orders
GROUP BY order_status #算的是每个状态的占比
ORDER BY order_count DESC, order_status;

-- Q02 全量月份覆盖。月份按下单时间，已交付数按来源状态统计。
SELECT DATE_FORMAT(order_purchase_timestamp, '%Y-%m') AS purchase_month,
       COUNT(*) AS placed_orders,
       SUM(CASE WHEN order_status = 'delivered' THEN 1 ELSE 0 END) AS delivered_orders,
       ROUND(100.0 * SUM(CASE WHEN order_status = 'delivered' THEN 1 ELSE 0 END)
             / COUNT(*), 2) AS delivered_pct,
       MIN(order_purchase_timestamp) AS first_purchase,
       MAX(order_purchase_timestamp) AS last_purchase
FROM orders
GROUP BY DATE_FORMAT(order_purchase_timestamp, '%Y-%m')
ORDER BY purchase_month;

-- Q03 全历史已交付经营基线。先汇总商品明细，再左关联订单。
WITH item_amount AS (
    SELECT order_id,
           SUM(price_cents) AS goods_cents,
           SUM(freight_cents) AS freight_cents
    FROM order_items
    GROUP BY order_id
)
SELECT COUNT(*) AS delivered_orders,
       COUNT(i.order_id) AS orders_with_item_amount,
       COUNT(*) - COUNT(i.order_id) AS missing_item_orders,
       ROUND(SUM(i.goods_cents) / 100.0, 2) AS goods_gmv_brl,
       ROUND(SUM(i.freight_cents) / 100.0, 2) AS freight_brl,
       ROUND(SUM(i.goods_cents) / (100.0 * NULLIF(COUNT(i.order_id), 0)), 2) AS goods_aov_brl#平均客单价
FROM orders AS o
LEFT JOIN item_amount AS i ON o.order_id = i.order_id
WHERE o.order_status = 'delivered';

-- Q04 主窗口的月度经营基线。包含 2018 年 8 月的最后一天。
WITH item_amount AS (
    SELECT order_id,
           SUM(price_cents) AS goods_cents,
           SUM(freight_cents) AS freight_cents
    FROM order_items
    GROUP BY order_id
),
delivered_orders_in_window AS (
    SELECT order_id, DATE_FORMAT(order_purchase_timestamp, '%Y-%m') AS purchase_month
    FROM orders
    WHERE order_status = 'delivered'
      AND order_purchase_timestamp >= '2017-01-01'
      AND order_purchase_timestamp <  '2018-09-01'
)
SELECT o.purchase_month,
       COUNT(*) AS delivered_orders,
       COUNT(*) - COUNT(i.order_id) AS missing_item_orders,
       ROUND(SUM(i.goods_cents) / 100.0, 2) AS goods_gmv_brl,
       ROUND(SUM(i.freight_cents) / 100.0, 2) AS freight_brl,
       ROUND(SUM(i.goods_cents) / (100.0 * NULLIF(COUNT(i.order_id), 0)), 2) AS goods_aov_brl
FROM delivered_orders_in_window AS o
LEFT JOIN item_amount AS i ON o.order_id = i.order_id
GROUP BY o.purchase_month
ORDER BY o.purchase_month;
