USE olist_operations_analytics;

-- Q15 计算客户 RFM 基础指标，展示商品金额最高的 10 位客户。
WITH analysis_window AS (
    SELECT CAST('2017-01-01' AS DATETIME) AS window_start,
           CAST('2018-09-01' AS DATETIME) AS snapshot_at
),
order_amount AS (
    -- 一笔订单可能有多条商品明细，先把金额汇成一行一单。
    SELECT order_id, SUM(price_cents) AS goods_cents
    FROM order_items
    GROUP BY order_id
),
customer_rfm AS (
    SELECT c.customer_unique_id,
           MAX(o.order_purchase_timestamp) AS last_purchase_at,
           COUNT(*) AS frequency,
           COUNT(*) - COUNT(a.order_id) AS missing_item_orders,
           -- 保留缺明细的订单来算 R 和 F。若有金额缺失，整位客户的 M 留空。
           CASE WHEN COUNT(a.order_id) = COUNT(*) THEN SUM(a.goods_cents) END AS goods_cents
    FROM orders AS o
    JOIN customers AS c ON o.customer_id = c.customer_id
    LEFT JOIN order_amount AS a ON o.order_id = a.order_id
    CROSS JOIN analysis_window AS w
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= w.window_start
      AND o.order_purchase_timestamp <  w.snapshot_at
    GROUP BY c.customer_unique_id
)
SELECT r.customer_unique_id,
       DATE(r.last_purchase_at) AS last_purchase_date,
       -- DATEDIFF 按日历日期相减，基准日固定为观察窗口结束日。
       DATEDIFF(w.snapshot_at, r.last_purchase_at) AS recency_days,
       r.frequency,
       ROUND(r.goods_cents / 100.0, 2) AS monetary_brl,
       r.missing_item_orders
FROM customer_rfm AS r
CROSS JOIN analysis_window AS w
ORDER BY r.goods_cents DESC, r.customer_unique_id
LIMIT 10;
