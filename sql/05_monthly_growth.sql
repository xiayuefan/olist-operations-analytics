USE olist_operations_analytics;

-- Q05 经营指标环比。LAG 取排序后的上一行，再检查它是否为相邻月份。
WITH item_amount AS (
    SELECT order_id, SUM(price_cents) AS goods_cents
    FROM order_items
    GROUP BY order_id
),
monthly AS (
    SELECT CAST(DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m-01') AS DATE) AS purchase_month,
           COUNT(i.order_id) AS priced_orders,
           SUM(i.goods_cents) AS goods_cents
    FROM orders AS o
    LEFT JOIN item_amount AS i ON o.order_id = i.order_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-09-01'
    GROUP BY CAST(DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m-01') AS DATE)
),
with_previous AS (
    SELECT monthly.*,
           LAG(purchase_month) OVER months AS previous_month,
           LAG(priced_orders) OVER months AS previous_orders,
           LAG(goods_cents) OVER months AS previous_goods_cents
    FROM monthly
    WINDOW months AS (ORDER BY purchase_month)
)
SELECT DATE_FORMAT(purchase_month, '%Y-%m') AS purchase_month,
       priced_orders AS orders_with_item_amount,
       ROUND(goods_cents / 100.0, 2) AS goods_gmv_brl,
       ROUND(goods_cents / (100.0 * NULLIF(priced_orders, 0)), 2) AS goods_aov_brl,
       CASE WHEN DATE_ADD(previous_month, INTERVAL 1 MONTH) = purchase_month
            THEN ROUND(100.0 * (CAST(priced_orders AS SIGNED) - previous_orders)
                       / NULLIF(previous_orders, 0), 2) END AS order_count_mom_pct,
       CASE WHEN DATE_ADD(previous_month, INTERVAL 1 MONTH) = purchase_month
            THEN ROUND(100.0 * (goods_cents - previous_goods_cents)
                       / NULLIF(previous_goods_cents, 0), 2) END AS goods_gmv_mom_pct,
       CASE WHEN DATE_ADD(previous_month, INTERVAL 1 MONTH) = purchase_month
            THEN ROUND(100.0 * (goods_cents * previous_orders - previous_goods_cents * priced_orders)
                       / NULLIF(previous_goods_cents * priced_orders, 0), 2) END AS goods_aov_mom_pct
FROM with_previous
ORDER BY purchase_month;

-- Q06 成交额变化拆解。先按上月客单价计算订单量贡献，再分配剩余差额。
WITH item_amount AS (
    SELECT order_id, SUM(price_cents) AS goods_cents
    FROM order_items
    GROUP BY order_id
),
monthly AS (
    SELECT CAST(DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m-01') AS DATE) AS purchase_month,
           COUNT(i.order_id) AS priced_orders,
           SUM(i.goods_cents) AS goods_cents
    FROM orders AS o
    LEFT JOIN item_amount AS i ON o.order_id = i.order_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-09-01'
    GROUP BY CAST(DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m-01') AS DATE)
),
with_previous AS (
    SELECT monthly.*,
           LAG(purchase_month) OVER months AS previous_month,
           LAG(priced_orders) OVER months AS previous_orders,
           LAG(goods_cents) OVER months AS previous_goods_cents
    FROM monthly
    WINDOW months AS (ORDER BY purchase_month)
),
effects AS (
    SELECT purchase_month, previous_goods_cents, goods_cents,
           CASE WHEN DATE_ADD(previous_month, INTERVAL 1 MONTH) = purchase_month
                     AND previous_orders > 0 AND priced_orders > 0
                THEN goods_cents - previous_goods_cents END AS change_cents,
           CASE WHEN DATE_ADD(previous_month, INTERVAL 1 MONTH) = purchase_month
                     AND previous_orders > 0 AND priced_orders > 0
                THEN ROUND((CAST(priced_orders AS SIGNED) - previous_orders)
                           * CAST(previous_goods_cents AS DECIMAL(30, 10))
                           / NULLIF(previous_orders, 0), 0) END AS volume_effect_cents
    FROM with_previous
)
SELECT DATE_FORMAT(purchase_month, '%Y-%m') AS purchase_month,
       ROUND(previous_goods_cents / 100.0, 2) AS previous_gmv_brl,
       ROUND(goods_cents / 100.0, 2) AS current_gmv_brl,
       ROUND(change_cents / 100.0, 2) AS gmv_change_brl,
       ROUND(volume_effect_cents / 100.0, 2) AS order_count_effect_brl,
       ROUND((change_cents - volume_effect_cents) / 100.0, 2) AS aov_effect_brl
FROM effects
ORDER BY purchase_month;
