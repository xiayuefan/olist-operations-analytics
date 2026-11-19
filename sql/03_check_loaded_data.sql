USE olist_operations_analytics;

-- 逐表核对实际行数。转成有符号数后也能显示负差额。
SELECT table_name, expected_rows, actual_rows,
       CAST(actual_rows AS SIGNED) - expected_rows AS row_difference
FROM (
    SELECT 'customers' AS table_name, 99441 AS expected_rows, COUNT(*) AS actual_rows FROM customers
    UNION ALL SELECT 'sellers', 3095, COUNT(*) FROM sellers
    UNION ALL SELECT 'category_translation', 71, COUNT(*) FROM category_translation
    UNION ALL SELECT 'products', 32951, COUNT(*) FROM products
    UNION ALL SELECT 'geo_reference', 19019, COUNT(*) FROM geo_reference
    UNION ALL SELECT 'orders', 99441, COUNT(*) FROM orders
    UNION ALL SELECT 'order_items', 112650, COUNT(*) FROM order_items
    UNION ALL SELECT 'order_payments', 103886, COUNT(*) FROM order_payments
    UNION ALL SELECT 'order_reviews', 99224, COUNT(*) FROM order_reviews
) AS table_counts;

-- 金额沿用整数分，分别核对商品金额、运费与支付金额。
SELECT metric, expected_cents, actual_cents,
       actual_cents - expected_cents AS difference_cents
FROM (
    SELECT 'price_cents' AS metric, 1359164370 AS expected_cents,
           COALESCE(SUM(price_cents), 0) AS actual_cents FROM order_items
    UNION ALL SELECT 'freight_cents', 225190954, COALESCE(SUM(freight_cents), 0) FROM order_items
    UNION ALL SELECT 'payment_value_cents', 1600887212, COALESCE(SUM(payment_value_cents), 0) FROM order_payments
) AS amount_checks;

SELECT COUNT(*) AS products_with_unknown_weight_and_flag
FROM products
WHERE product_weight_g IS NULL AND flag_weight_zero IS NULL;
