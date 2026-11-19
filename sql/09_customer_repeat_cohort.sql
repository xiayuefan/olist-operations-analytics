USE olist_operations_analytics;

-- Q13 按窗口内首购月分组，计算可完整观察的 cohort 的 90 天复购率。
WITH observation_window AS (
    SELECT CAST('2017-01-01' AS DATETIME) AS window_start,
           CAST('2018-09-01' AS DATETIME) AS window_end
),
ordered_purchases AS (
    SELECT o.order_purchase_timestamp AS purchase_at,
           w.window_end,
           ROW_NUMBER() OVER customer_timeline AS purchase_rank,
           -- 在同一客户的时间线上取下一单。没有下一单时，LEAD 返回 NULL。
           LEAD(o.order_purchase_timestamp) OVER customer_timeline AS next_purchase_at
    FROM orders AS o
    JOIN customers AS c ON o.customer_id = c.customer_id
    CROSS JOIN observation_window AS w
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= w.window_start
      AND o.order_purchase_timestamp <  w.window_end
    WINDOW customer_timeline AS (
        PARTITION BY c.customer_unique_id
        ORDER BY o.order_purchase_timestamp, o.order_id
    )
),
first_purchases AS (
    -- 只保留每位客户的第一单，此时下一单就是该客户在窗口内的第二单。
    SELECT DATE_FORMAT(purchase_at, '%Y-%m') AS first_purchase_month,
           purchase_at + INTERVAL 90 DAY AS followup_ends_at,
           next_purchase_at AS second_purchase_at,
           window_end
    FROM ordered_purchases
    WHERE purchase_rank = 1
),
monthly_counts AS (
    SELECT first_purchase_month,
           COUNT(*) AS cohort_customers,
           -- 观察截止时刻本身不包含在数据中，90 天期限必须早于它。
           SUM(CASE WHEN followup_ends_at < window_end THEN 1 ELSE 0 END) AS eligible_customers,
           SUM(CASE WHEN second_purchase_at <= followup_ends_at THEN 1 ELSE 0 END) AS repeat_customers
    FROM first_purchases
    GROUP BY first_purchase_month
)
SELECT first_purchase_month,
       cohort_customers,
       eligible_customers,
       cohort_customers - eligible_customers AS pending_customers,
       -- 只发布整组可完整观察的月份，保留未成熟月份的客户数量。
       CASE WHEN eligible_customers = cohort_customers THEN repeat_customers END AS repeat_90d_customers,
       CASE WHEN eligible_customers = cohort_customers
            THEN ROUND(100.0 * repeat_customers / cohort_customers, 2) END AS repeat_90d_pct
FROM monthly_counts
ORDER BY first_purchase_month;
