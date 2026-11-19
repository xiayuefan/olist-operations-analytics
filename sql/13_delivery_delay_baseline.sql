USE olist_operations_analytics;

-- Q17 核对已交付订单中有多少能判断延迟，再计算延迟率。
WITH delivered_orders AS (
    -- 沿用 Python 清洗后的资格标记和自然日差。无法判断的订单仍计入总交付数。
    SELECT CASE WHEN is_valid_delay = 1 THEN delivery_delay_days END 
    AS delay_days #如果 `is_valid_delay=1`(`is_valid_delay = 1`：这一单的延迟天数 `delivery_delay_days` 是可信、可以用来做时效分析的)：输出真实延迟天数 `delivery_delay_days`如果 `is_valid_delay≠1`：返回 `NULL`
    FROM orders
    WHERE order_status = 'delivered'
      AND order_purchase_timestamp >= '2017-01-01'
      AND order_purchase_timestamp <  '2018-09-01'
),
delay_counts AS (
    SELECT COUNT(*) AS delivered_orders,
           COUNT(delay_days) AS valid_delay_orders,
           COUNT(CASE WHEN delay_days > 0 THEN 1 END) AS late_orders
    FROM delivered_orders
)
SELECT delivered_orders,
       valid_delay_orders,
       delivered_orders - valid_delay_orders AS unassessable_orders,
       late_orders,
       ROUND(100.0 * late_orders / NULLIF(valid_delay_orders, 0), 2) AS late_rate_pct#延迟率
FROM delay_counts;

-- Q18 只给可判断的订单分档。每笔订单只落入一档，按延迟程度排序。
WITH delay_bands AS (
    SELECT CASE WHEN delivery_delay_days <= 0 THEN 1#没延迟
                WHEN delivery_delay_days <= 3 THEN 2
                WHEN delivery_delay_days <= 7 THEN 3
                WHEN delivery_delay_days <= 14 THEN 4
                ELSE 5 END AS band_order
    FROM orders
    WHERE order_status = 'delivered'
      AND order_purchase_timestamp >= '2017-01-01'
      AND order_purchase_timestamp <  '2018-09-01'
      AND is_valid_delay = 1
      AND delivery_delay_days IS NOT NULL
),
band_counts AS (
    SELECT band_order, COUNT(*) AS order_count
    FROM delay_bands
    GROUP BY band_order
)
SELECT CASE band_order WHEN 1 THEN 'on_time_or_early'
                       WHEN 2 THEN '1_to_3_days_late'
                       WHEN 3 THEN '4_to_7_days_late'
                       WHEN 4 THEN '8_to_14_days_late'
                       ELSE '15_plus_days_late' END AS delay_band,
       order_count,
       -- 分母是所有档位的订单数，包括按时或提前的订单。
       ROUND(100.0 * order_count / SUM(order_count) OVER (), 2) AS share_of_valid_pct
FROM band_counts
ORDER BY band_order;
