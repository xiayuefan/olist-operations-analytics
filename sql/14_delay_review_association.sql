USE olist_operations_analytics;

-- Q19 按延迟档比较最新有效评分的覆盖率与低评分率。
WITH delay_bands AS (
    -- 沿用 Q18 的样本和分档，每行是一笔可判断延迟的订单。
    SELECT order_id,
           CASE WHEN delivery_delay_days <= 0 THEN 1
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
latest_review_times AS (
    -- 先找出每笔订单的最新评价时间。提交时间无法确认的订单留待核查。
    SELECT order_id, MAX(review_answer_timestamp) AS latest_answer_at
    FROM order_reviews
    GROUP BY order_id
    HAVING COUNT(review_answer_timestamp) = COUNT(*)
       AND MAX(flag_answer_before_creation) = 0
),
latest_order_reviews AS (
    -- 回到评价明细取评分。HAVING 只保留最新时间能唯一定位一条评价的订单。
    SELECT r.order_id, MAX(r.review_score) AS latest_review_score
    FROM order_reviews AS r
    JOIN latest_review_times AS t ON r.order_id = t.order_id
                                 AND r.review_answer_timestamp = t.latest_answer_at
    GROUP BY r.order_id
    HAVING COUNT(*) = 1
),
band_counts AS (
    SELECT d.band_order,
           COUNT(*) AS order_count,
           COUNT(r.latest_review_score) AS rated_orders,
           COUNT(CASE WHEN r.latest_review_score IN (1, 2) THEN 1 END) AS low_score_orders
    FROM delay_bands AS d
    -- 左关联保留无有效评分的订单，便于计算评价覆盖率。
    LEFT JOIN latest_order_reviews AS r ON d.order_id = r.order_id
    GROUP BY d.band_order
)
SELECT CASE band_order WHEN 1 THEN 'on_time_or_early'
                       WHEN 2 THEN '1_to_3_days_late'
                       WHEN 3 THEN '4_to_7_days_late'
                       WHEN 4 THEN '8_to_14_days_late'
                       ELSE '15_plus_days_late' END AS delay_band,
       order_count,
       rated_orders,
       order_count - rated_orders AS orders_without_valid_review,
       low_score_orders,
       ROUND(100.0 * rated_orders / order_count, 2) AS review_coverage_pct,
       ROUND(100.0 * low_score_orders / NULLIF(rated_orders, 0), 2) AS low_score_rate_pct
FROM band_counts
ORDER BY band_order;
