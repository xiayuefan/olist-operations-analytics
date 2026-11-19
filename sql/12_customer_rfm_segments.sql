USE olist_operations_analytics;

-- Q16 先按 F 区分单次购买和复购，再在各组内按 R 和 M 划分客户。
WITH analysis_window AS (
    SELECT CAST('2017-01-01' AS DATETIME) AS window_start,
           CAST('2018-09-01' AS DATETIME) AS snapshot_at
),
order_amount AS (
    -- 和 Q15 一样，先汇总到订单粒度，避免一笔订单被重复计数。
    SELECT order_id, SUM(price_cents) AS goods_cents
    FROM order_items
    GROUP BY order_id
),
customer_rfm AS (
    SELECT c.customer_unique_id,
           DATEDIFF(w.snapshot_at, MAX(o.order_purchase_timestamp)) AS recency_days,
           COUNT(*) AS frequency,
           CASE WHEN COUNT(a.order_id) = COUNT(*) THEN SUM(a.goods_cents) END AS goods_cents
    FROM orders AS o
    JOIN customers AS c ON o.customer_id = c.customer_id
    LEFT JOIN order_amount AS a ON o.order_id = a.order_id
    CROSS JOIN analysis_window AS w
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= w.window_start
      AND o.order_purchase_timestamp <  w.snapshot_at
    GROUP BY c.customer_unique_id, w.snapshot_at
),
frequency_groups AS (
    -- F=1 的客户集中在同一组，不用名次把相同的购买次数分开。
    SELECT CASE WHEN frequency = 1 THEN 'one_time' ELSE 'repeat' END AS frequency_group,
           recency_days,
           frequency,
           goods_cents
    FROM customer_rfm
),
monetary_distribution AS (
    -- CUME_DIST 是组内金额小于等于当前金额的客户占比。同金额得到相同的占比。
    SELECT frequency_group,
           goods_cents,
           CUME_DIST() OVER (PARTITION BY frequency_group ORDER BY goods_cents) AS cumulative_share
    FROM frequency_groups
    WHERE goods_cents IS NOT NULL
),
monetary_cutoffs AS (
    SELECT frequency_group, MIN(goods_cents) AS p75_cents
    FROM monetary_distribution
    WHERE cumulative_share >= 0.75
    GROUP BY frequency_group
),
segmented_customers AS (
    SELECT f.frequency_group,
           CASE WHEN f.recency_days <= 90 THEN 'within_90d' ELSE 'over_90d' END AS recency_group,
           CASE WHEN f.goods_cents IS NULL THEN 'unknown_m'
                WHEN f.goods_cents >= m.p75_cents THEN 'at_or_above_p75'
                ELSE 'below_p75' END AS monetary_group,
           m.p75_cents,
           f.frequency,
           f.goods_cents
    FROM frequency_groups AS f
    LEFT JOIN monetary_cutoffs AS m ON f.frequency_group = m.frequency_group
)
SELECT frequency_group,
       recency_group,
       monetary_group,
       ROUND(p75_cents / 100.0, 2) AS m_cutoff_brl,
       COUNT(*) AS customer_count,
       SUM(frequency) AS delivered_orders,
       ROUND(SUM(goods_cents) / 100.0, 2) AS goods_gmv_brl
FROM segmented_customers
GROUP BY frequency_group, recency_group, monetary_group, p75_cents
ORDER BY frequency_group, recency_group, monetary_group;
