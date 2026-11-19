USE olist_operations_analytics;

-- 首次建表完成后，预期得到 9 张表、9 个主键和 6 条外键。
SELECT
    (SELECT COUNT(*) FROM information_schema.TABLES
      WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE') AS table_count,
    (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
      WHERE TABLE_SCHEMA = DATABASE() AND CONSTRAINT_TYPE = 'PRIMARY KEY') AS primary_key_count,
    (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
      WHERE TABLE_SCHEMA = DATABASE() AND CONSTRAINT_TYPE = 'FOREIGN KEY') AS foreign_key_count;

SELECT TABLE_NAME AS table_name,
       GROUP_CONCAT(COLUMN_NAME ORDER BY ORDINAL_POSITION SEPARATOR ' + ') AS primary_key_columns
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = DATABASE() AND CONSTRAINT_NAME = 'PRIMARY'
GROUP BY TABLE_NAME
ORDER BY TABLE_NAME;

SELECT TABLE_NAME AS child_table, COLUMN_NAME AS child_column,
       REFERENCED_TABLE_NAME AS parent_table, REFERENCED_COLUMN_NAME AS parent_column
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_SCHEMA = DATABASE()
ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION;

-- 三个例子分别核对邮编、整数分金额和可空标记的字段类型。
SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name,
       COLUMN_TYPE AS column_type, IS_NULLABLE AS is_nullable
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND ((TABLE_NAME = 'customers' AND COLUMN_NAME = 'customer_zip_code_prefix')
    OR (TABLE_NAME = 'order_items' AND COLUMN_NAME = 'price_cents')
    OR (TABLE_NAME = 'products' AND COLUMN_NAME = 'flag_weight_zero'))
ORDER BY TABLE_NAME;

-- COUNT(*) 返回实际行数，方便与下一课装载后的结果比较。
SELECT 'customers' AS table_name, COUNT(*) AS row_count FROM customers
UNION ALL SELECT 'sellers', COUNT(*) FROM sellers
UNION ALL SELECT 'category_translation', COUNT(*) FROM category_translation
UNION ALL SELECT 'products', COUNT(*) FROM products
UNION ALL SELECT 'geo_reference', COUNT(*) FROM geo_reference
UNION ALL SELECT 'orders', COUNT(*) FROM orders
UNION ALL SELECT 'order_items', COUNT(*) FROM order_items
UNION ALL SELECT 'order_payments', COUNT(*) FROM order_payments
UNION ALL SELECT 'order_reviews', COUNT(*) FROM order_reviews;
