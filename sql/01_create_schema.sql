-- 从 config/mysql_input_v1.json 生成。按父表在前、子表在后的顺序建表。
CREATE DATABASE IF NOT EXISTS `olist_operations_analytics` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin;
#default character set utf8mb4:默认字符集utf8mb4
#collate utf8mb4_0900_bin二进制比较区分大小写，不区分：utf8mb4_0900_ai_ci

-- 切换当前会话，使用这个数据库
USE `olist_operations_analytics`;

-- 一个订单关联的客户记录
CREATE TABLE IF NOT EXISTS `customers` (
    `customer_id` CHAR(32) NOT NULL,
    `customer_unique_id` CHAR(32) NOT NULL,
    `customer_zip_code_prefix` CHAR(5) NOT NULL,
    `customer_state` CHAR(2) NOT NULL,
    `customer_city` VARCHAR(128) NOT NULL,
    `flag_zip_format_invalid` TINYINT NOT NULL,
    `flag_state_format_invalid` TINYINT NOT NULL,  
     #`TINYINT` 存 0/1 标志位
    `flag_state_unknown` TINYINT NOT NULL,
    `flag_city_missing` TINYINT NOT NULL,
    `flag_customer_location_needs_review` TINYINT NOT NULL,
    `can_group_by_city_state` TINYINT NOT NULL,
    PRIMARY KEY (`customer_id`)
) ENGINE=InnoDB #InnoDB 引擎
 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin;

-- 一个卖家
CREATE TABLE IF NOT EXISTS `sellers` (
    `seller_id` CHAR(32) NOT NULL,
    `seller_zip_code_prefix` CHAR(5) NOT NULL,
    `seller_state` CHAR(2) NOT NULL,
    `seller_city` VARCHAR(128) NOT NULL,
    `flag_zip_format_invalid` TINYINT NOT NULL,
    `flag_state_format_invalid` TINYINT NOT NULL,
    `flag_state_unknown` TINYINT NOT NULL,
    `flag_city_missing` TINYINT NOT NULL,
    PRIMARY KEY (`seller_id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin;

-- 一个原始品类的英文映射
CREATE TABLE IF NOT EXISTS `category_translation` (
    `product_category_name` VARCHAR(128) NOT NULL,
    `product_category_name_english` VARCHAR(128) NOT NULL,
    PRIMARY KEY (`product_category_name`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin;

-- 一个商品
CREATE TABLE IF NOT EXISTS `products` (
    `product_id` CHAR(32) NOT NULL,
    `product_category_name` VARCHAR(128) NULL,
    `product_name_lenght` INT NULL,
    `product_description_lenght` INT NULL,
    `product_photos_qty` INT NULL,
    `product_weight_g` INT NULL,
    `product_length_cm` INT NULL,
    `product_height_cm` INT NULL,
    `product_width_cm` INT NULL,
    `product_volume_cm3` INT NULL,
    `flag_category_missing` TINYINT NOT NULL,
    `flag_category_untranslated` TINYINT NOT NULL,
    `flag_weight_missing` TINYINT NOT NULL,
    `flag_weight_zero` TINYINT NULL,
    `can_use_weight` TINYINT NOT NULL,
    `flag_content_metadata_missing` TINYINT NOT NULL,
    `flag_dimensions_missing` TINYINT NOT NULL,
    `flag_dimensions_nonpositive` TINYINT NOT NULL,
    `can_calculate_volume` TINYINT NOT NULL,
    PRIMARY KEY (`product_id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin;

-- 一个邮编前缀与州组合的代表坐标
CREATE TABLE IF NOT EXISTS `geo_reference` (
    `geolocation_zip_code_prefix` CHAR(5) NOT NULL,
    `geolocation_state` CHAR(2) NOT NULL,
    `representative_latitude` DOUBLE NOT NULL,
    `representative_longitude` DOUBLE NOT NULL,
    `candidate_record_count` INT NOT NULL,
    `candidate_city_label_count` INT NOT NULL,
    PRIMARY KEY (`geolocation_zip_code_prefix`, `geolocation_state`)
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin;

-- 一笔订单
CREATE TABLE IF NOT EXISTS `orders` (
    `order_id` CHAR(32) NOT NULL,
    `customer_id` CHAR(32) NOT NULL,
    `order_status` VARCHAR(128) NOT NULL,
    `order_purchase_timestamp` DATETIME NOT NULL,
    `order_approved_at` DATETIME NULL,
    `order_delivered_carrier_date` DATETIME NULL,
    `order_delivered_customer_date` DATETIME NULL,
    `order_estimated_delivery_date` DATETIME NOT NULL,
    `flag_delivered_missing_date` TINYINT NOT NULL,
    `flag_delivered_missing_approval` TINYINT NOT NULL,
    `flag_delivered_missing_carrier` TINYINT NOT NULL,
    `flag_carrier_before_purchase` TINYINT NOT NULL,
    `flag_delivery_before_carrier` TINYINT NOT NULL,
    `flag_canceled_has_delivery_date` TINYINT NOT NULL,
    `flag_approval_before_purchase` TINYINT NOT NULL,
    `flag_carrier_before_approval` TINYINT NOT NULL,
    `flag_needs_review` TINYINT NOT NULL,
    `is_valid_transit` TINYINT NOT NULL,
    `is_valid_delay` TINYINT NOT NULL,
    `review_rule_count` INT NOT NULL,
    `delivery_delay_days` INT NULL,
    `transit_days_raw` DOUBLE NULL,
    `transit_days` DOUBLE NULL,
    PRIMARY KEY (`order_id`),
    CONSTRAINT `fk_orders_customers` #外键约束命名为 `fk_orders_customers`
    FOREIGN KEY (`customer_id`) REFERENCES `customers` (`customer_id`) ON UPDATE RESTRICT ON DELETE RESTRICT#限制父表customers主键被修改、删除
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin;

-- 一笔订单中的一条商品明细
CREATE TABLE IF NOT EXISTS `order_items` (
    `order_id` CHAR(32) NOT NULL,
    `product_id` CHAR(32) NOT NULL,
    `seller_id` CHAR(32) NOT NULL,
    `order_item_id` INT NOT NULL,
    `shipping_limit_date` DATETIME NULL,
    `price_cents` BIGINT NOT NULL,
    `freight_cents` BIGINT NOT NULL,
    `flag_missing_shipping_limit_date` TINYINT NOT NULL,
    `flag_zero_price` TINYINT NOT NULL,
    `is_zero_freight` TINYINT NOT NULL,
    PRIMARY KEY (`order_id`, `order_item_id`),
    CONSTRAINT `fk_order_items_orders` FOREIGN KEY (`order_id`) REFERENCES `orders` (`order_id`) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk_order_items_products` FOREIGN KEY (`product_id`) REFERENCES `products` (`product_id`) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT `fk_order_items_sellers` FOREIGN KEY (`seller_id`) REFERENCES `sellers` (`seller_id`) ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin;

-- 一笔订单的一条支付记录
CREATE TABLE IF NOT EXISTS `order_payments` (
    `order_id` CHAR(32) NOT NULL,
    `payment_sequential` INT NOT NULL,
    `payment_installments` INT NOT NULL,
    `payment_type` VARCHAR(128) NOT NULL,
    `payment_value_cents` BIGINT NOT NULL,
    `flag_zero_payment` TINYINT NOT NULL,
    `flag_payment_type_not_defined` TINYINT NOT NULL,
    `flag_zero_installments` TINYINT NOT NULL,
    `flag_payment_needs_review` TINYINT NOT NULL,
    PRIMARY KEY (`order_id`, `payment_sequential`),
    CONSTRAINT `fk_order_payments_orders` FOREIGN KEY (`order_id`) REFERENCES `orders` (`order_id`) ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin;

-- 一笔订单的一条评价记录
CREATE TABLE IF NOT EXISTS `order_reviews` (
    `order_id` CHAR(32) NOT NULL,
    `review_id` CHAR(32) NOT NULL,
    `review_score` INT NOT NULL,
    `review_comment_title` TEXT NULL,
    `review_comment_message` TEXT NULL,
    `review_creation_date` DATETIME NULL,
    `review_answer_timestamp` DATETIME NULL,
    `is_low_score` TINYINT NOT NULL,
    `has_comment_title` TINYINT NOT NULL,
    `has_comment_message` TINYINT NOT NULL,
    `flag_missing_creation_date` TINYINT NOT NULL,
    `flag_missing_answer_timestamp` TINYINT NOT NULL,
    `can_compare_review_time` TINYINT NOT NULL,
    `flag_answer_before_creation` TINYINT NOT NULL,
    `flag_review_time_needs_review` TINYINT NOT NULL,
    `review_answer_lag_days` DOUBLE NULL,
    PRIMARY KEY (`order_id`, `review_id`),
    CONSTRAINT `fk_order_reviews_orders` FOREIGN KEY (`order_id`) REFERENCES `orders` (`order_id`) ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin;
