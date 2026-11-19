USE olist_operations_analytics;

-- Q09 按客户所在州比较订单规模、商品成交额和商品客单价。
WITH order_amount AS (
    SELECT order_id, SUM(price_cents) AS goods_cents
    FROM order_items
    GROUP BY order_id
),
state_sales AS (
    SELECT c.customer_state,
           COUNT(*) AS delivered_orders,
           COUNT(a.order_id) AS priced_orders,
           SUM(a.goods_cents) AS goods_cents
    FROM orders AS o
    JOIN customers AS c ON o.customer_id = c.customer_id
    LEFT JOIN order_amount AS a ON o.order_id = a.order_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-09-01'
    GROUP BY c.customer_state
)
SELECT customer_state,
       delivered_orders,
       delivered_orders - priced_orders AS missing_item_orders,
       ROUND(goods_cents / 100.0, 2) AS goods_gmv_brl,
       ROUND(goods_cents / (100.0 * NULLIF(priced_orders, 0)), 2) AS goods_aov_brl,
       ROUND(100.0 * delivered_orders / NULLIF(SUM(delivered_orders) OVER (), 0), 2) AS order_share_pct,
       ROUND(100.0 * goods_cents / NULLIF(SUM(goods_cents) OVER (), 0), 2) AS gmv_share_pct
FROM state_sales
ORDER BY goods_cents DESC, customer_state;

-- Q10 按客户所在州拆解 2017 年 11 月相对 10 月的商品成交额变化。
-- 每条商品明细通过所属订单取得客户州，两个月金额在同一州分组中计算。
WITH state_months AS (
    SELECT c.customer_state,
           SUM(CASE WHEN o.order_purchase_timestamp < '2017-11-01'
                    THEN i.price_cents ELSE 0 END) AS october_cents,
           SUM(CASE WHEN o.order_purchase_timestamp >= '2017-11-01'
                    THEN i.price_cents ELSE 0 END) AS november_cents
    FROM orders AS o
    JOIN customers AS c ON o.customer_id = c.customer_id
    JOIN order_items AS i ON o.order_id = i.order_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= '2017-10-01'
      AND o.order_purchase_timestamp <  '2017-12-01'
    GROUP BY c.customer_state
),
state_change AS (
    SELECT state_months.*,
           november_cents - october_cents AS change_cents,
           SUM(november_cents - october_cents) OVER () AS total_change_cents
    FROM state_months
)
SELECT customer_state,
       ROUND(october_cents / 100.0, 2) AS october_gmv_brl,
       ROUND(november_cents / 100.0, 2) AS november_gmv_brl,
       ROUND(change_cents / 100.0, 2) AS change_brl,
       ROUND(100.0 * change_cents / NULLIF(total_change_cents, 0), 2) AS net_change_share_pct,
       ROUND(total_change_cents / 100.0, 2) AS total_change_brl
FROM state_change
ORDER BY change_cents DESC, customer_state;
