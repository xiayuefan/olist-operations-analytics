USE olist_operations_analytics;

-- Q14 比较同一首购月在 30、60、90 天内的累计复购率。
WITH observation_window AS (
    SELECT CAST('2017-01-01' AS DATETIME) AS window_start,
           CAST('2018-09-01' AS DATETIME) AS window_end
),
followup_windows AS (
    SELECT 30 AS followup_days
    UNION ALL SELECT 60
    UNION ALL SELECT 90
),
ordered_purchases AS (
    SELECT o.order_purchase_timestamp AS purchase_at,
           w.window_end,
           ROW_NUMBER() OVER customer_timeline AS purchase_rank,
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
customer_windows AS (
    -- 每位客户只保留首单，再用 CROSS JOIN 让同一客户分别进入三个观察期限。
    SELECT DATE_FORMAT(p.purchase_at, '%Y-%m') AS first_purchase_month, #p.purchase_rank = 1等于1，p.purchase_at首次购买的时间
           f.followup_days,
           p.purchase_at + INTERVAL f.followup_days DAY AS followup_ends_at,
           p.next_purchase_at AS second_purchase_at,
           p.window_end
    FROM ordered_purchases AS p
    CROSS JOIN followup_windows AS f
    WHERE p.purchase_rank = 1
),
monthly_counts AS (
    -- 每个首购月、每个期限各自判断观察期是否完整。
    SELECT first_purchase_month,
           followup_days,
           COUNT(*) AS cohort_customers,
           SUM(CASE WHEN followup_ends_at < window_end THEN 1 ELSE 0 END) AS eligible_customers,
           SUM(CASE WHEN second_purchase_at <= followup_ends_at THEN 1 ELSE 0 END) AS repeat_customers
    FROM customer_windows
    GROUP BY first_purchase_month, followup_days
)
SELECT first_purchase_month,
       followup_days,
       cohort_customers,
       eligible_customers,
       cohort_customers - eligible_customers AS pending_customers,
       CASE WHEN eligible_customers = cohort_customers THEN repeat_customers END AS repeat_customers,
       CASE WHEN eligible_customers = cohort_customers
            THEN ROUND(100.0 * repeat_customers / cohort_customers, 2) END AS repeat_pct
FROM monthly_counts
ORDER BY first_purchase_month, followup_days;
