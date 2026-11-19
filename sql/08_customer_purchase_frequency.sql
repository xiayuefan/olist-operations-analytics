USE olist_operations_analytics;

-- Q11 按客户统计窗口内的下单次数，再汇总各频次的客户数和订单数。
WITH customer_order_counts AS (
    SELECT c.customer_unique_id,
           COUNT(*) AS order_count
    FROM orders AS o
    -- customer_id 用来找到该笔订单对应的客户记录。
    JOIN customers AS c ON o.customer_id = c.customer_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-09-01'
    -- 同一客户的不同订单可能用了不同的 customer_id，在这里合并计数。
    GROUP BY c.customer_unique_id
),
frequency_groups AS (
    SELECT LEAST(order_count, 4) AS frequency_group,
           COUNT(*) AS customer_count,
           SUM(order_count) AS delivered_orders
    FROM customer_order_counts
    GROUP BY LEAST(order_count, 4)
)
SELECT CASE WHEN frequency_group = 4 THEN '4+'
            ELSE CAST(frequency_group AS CHAR) END AS orders_per_customer,
       customer_count,
       delivered_orders,
       ROUND(100.0 * customer_count / SUM(customer_count) OVER (), 2) AS customer_share_pct
FROM frequency_groups
ORDER BY frequency_group;

-- Q12 每月区分窗口内首次购买订单和后续购买订单。
WITH ranked_orders AS (
    SELECT o.order_purchase_timestamp,
           -- 给每位客户从 1 开始编号。下单时间相同则按订单 ID 固定顺序。
           ROW_NUMBER() OVER (
               PARTITION BY c.customer_unique_id
               ORDER BY o.order_purchase_timestamp, o.order_id#-按**同一个唯一客户**分组，同一个客户的订单，按时间先后排序
           ) AS purchase_rank
    FROM orders AS o
    JOIN customers AS c ON o.customer_id = c.customer_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-09-01'
)
SELECT DATE_FORMAT(order_purchase_timestamp, '%Y-%m') AS purchase_month,
       COUNT(*) AS delivered_orders,
       SUM(CASE WHEN purchase_rank = 1 THEN 1 ELSE 0 END) AS first_purchase_orders,#客户历史首单
       SUM(CASE WHEN purchase_rank > 1 THEN 1 ELSE 0 END) AS later_purchase_orders,
       ROUND(100.0 * SUM(CASE WHEN purchase_rank > 1 THEN 1 ELSE 0 END)
             / COUNT(*), 2) AS later_order_share_pct#复购订单占当月订单的比例（%）
FROM ranked_orders
-- 先跨月给每单编号，再按下单月汇总。跨月购买的客户不会在每月重新编号。
GROUP BY DATE_FORMAT(order_purchase_timestamp, '%Y-%m')
ORDER BY purchase_month;
