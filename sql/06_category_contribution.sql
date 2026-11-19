USE olist_operations_analytics;

-- Q07 品类成交额结构与累计占比。每条商品明细的金额归到一个品类组。
WITH category_sales AS (
    SELECT p.product_category_name,
           COUNT(*) AS item_lines,
           COUNT(DISTINCT i.order_id) AS category_orders,
           SUM(i.price_cents) AS goods_cents
    FROM orders AS o
    JOIN order_items AS i ON o.order_id = i.order_id
    JOIN products AS p ON i.product_id = p.product_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= '2017-01-01'
      AND o.order_purchase_timestamp <  '2018-09-01'
    GROUP BY p.product_category_name
),
ranked AS (
    SELECT category_sales.*,
           ROW_NUMBER() OVER (ORDER BY goods_cents DESC, product_category_name) AS gmv_rank,#按销售额降序，销售额相同按类目名字升序，打排名（ROW_NUMBER：不并列）
           SUM(goods_cents) OVER () AS total_goods_cents,#全部类目总销售额（全局窗口，不分区）
           SUM(goods_cents) OVER (
               ORDER BY goods_cents DESC, product_category_name
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS cumulative_cents#累计销售额：从上到下累加（按销售额降序排好之后逐行累加）
    FROM category_sales
)
SELECT r.gmv_rank,
       COALESCE(r.product_category_name, '(missing)') AS category_key,
       COALESCE(t.product_category_name_english, r.product_category_name, '(missing)') AS category_label,
       CASE WHEN r.product_category_name IS NULL THEN 'source_missing'
            WHEN t.product_category_name IS NULL THEN 'translation_missing'
            ELSE 'translated' END AS category_mapping,
       r.item_lines,
       r.category_orders,
       ROUND(r.goods_cents / 100.0, 2) AS goods_gmv_brl,
       ROUND(100.0 * r.goods_cents / NULLIF(r.total_goods_cents, 0), 2) AS gmv_share_pct,#贡献比
       ROUND(100.0 * r.cumulative_cents / NULLIF(r.total_goods_cents, 0), 2) AS cumulative_gmv_pct,#累计贡献比
       CASE WHEN r.cumulative_cents >= 0.8 * r.total_goods_cents
                  AND r.cumulative_cents - r.goods_cents < 0.8 * r.total_goods_cents
            THEN 1 ELSE 0 END AS crosses_80_pct #当前行累计 ≥ 80% 总 GMV并且**上一行累计（当前累计减去自己这个类目的 GMV）＜80%**
FROM ranked AS r
LEFT JOIN category_translation AS t ON r.product_category_name = t.product_category_name
ORDER BY r.gmv_rank;

-- Q08 按品类拆解 2017 年 11 月相对 10 月的商品成交额变化。
-- 同一组内分别汇总两个月，保留只在其中一个月出现的品类。
WITH category_months AS (
    SELECT p.product_category_name,
           SUM(CASE WHEN o.order_purchase_timestamp < '2017-11-01'
                    THEN i.price_cents ELSE 0 END) AS october_cents,
           SUM(CASE WHEN o.order_purchase_timestamp >= '2017-11-01'
                    THEN i.price_cents ELSE 0 END) AS november_cents
    FROM orders AS o
    JOIN order_items AS i ON o.order_id = i.order_id
    JOIN products AS p ON i.product_id = p.product_id
    WHERE o.order_status = 'delivered'
      AND o.order_purchase_timestamp >= '2017-10-01'
      AND o.order_purchase_timestamp <  '2017-12-01'
    GROUP BY p.product_category_name
),
category_change AS (
    SELECT category_months.*,
           november_cents - october_cents AS change_cents,
           SUM(november_cents - october_cents) OVER () AS total_change_cents
    FROM category_months
)
SELECT COALESCE(c.product_category_name, '(missing)') AS category_key,
       COALESCE(t.product_category_name_english, c.product_category_name, '(missing)') AS category_label,
       ROUND(c.october_cents / 100.0, 2) AS october_gmv_brl,
       ROUND(c.november_cents / 100.0, 2) AS november_gmv_brl,
       ROUND(c.change_cents / 100.0, 2) AS change_brl,
       ROUND(100.0 * c.change_cents / NULLIF(c.total_change_cents, 0), 2) AS net_change_share_pct,
       ROUND(c.total_change_cents / 100.0, 2) AS total_change_brl
FROM category_change AS c
LEFT JOIN category_translation AS t ON c.product_category_name = t.product_category_name
ORDER BY c.change_cents DESC, c.product_category_name;
