# MySQL 入库准备

入库清单位于 config/mysql_input_v1.json。它记录九张表的清洗来源、行数、粒度、主键、字段类型、可空字段和拟用关联。第 22 份 Notebook 从清单读取并验证现有 CSV。

| 表 | 一行代表什么 | 主键 |
| --- | --- | --- |
| customers | 一个订单关联的客户记录 | customer_id |
| sellers | 一个卖家 | seller_id |
| category_translation | 一个原始品类的英文映射 | product_category_name |
| products | 一个商品 | product_id |
| geo_reference | 一个邮编前缀与州组合的代表坐标 | geolocation_zip_code_prefix + geolocation_state |
| orders | 一笔订单 | order_id |
| order_items | 一条订单商品明细 | order_id + order_item_id |
| order_payments | 一条订单支付记录 | order_id + payment_sequential |
| order_reviews | 一条订单评价记录 | order_id + review_id |

订单选用 v2，保留审批时间相关的质量标记。商品原始品类保留在商品表，英文映射从品类翻译表取得。商品金额、运费和支付额各使用清洗生成的整数分字段。订单商品汇总、支付汇总和评价汇总可以从各自的明细重新生成。

| 字段 | 拟用 MySQL 类型 | 本项目的口径 |
| --- | --- | --- |
| 订单、客户、卖家、商品及评价 ID | CHAR(32) | 固定长度文本 |
| 邮编前缀、州缩写 | CHAR(5)、CHAR(2) | 保留邮编前导零 |
| 商品金额、运费、支付额 | BIGINT | 巴西雷亚尔的整数分 |
| 计数、序号、尺寸整数 | INT | 根据清单保留空值 |
| 时间字段 | DATETIME | 按来源日期时间读取 |
| 坐标与带小数的天数 | DOUBLE | 保存近似数值 |
| 质量标记 | TINYINT | Pandas 中保留可空布尔，SQL 装载时转换为 0、1 或 NULL |
| 城市、品类、状态和支付方式 | VARCHAR(128) | 保存原字段文本 |
| 评价标题与内容 | TEXT | 保存评价文字和缺失状态 |

类型参考 MySQL 8.0 手册的[整数类型](https://dev.mysql.com/doc/refman/8.0/en/integer-types.html)、[日期时间类型](https://dev.mysql.com/doc/refman/8.0/en/datetime.html)和[字符类型](https://dev.mysql.com/doc/refman/8.0/en/char.html)。字段长度及可空性是本项目的入库约定。

订单通过 customer_id 关联客户。商品明细通过 order_id、product_id、seller_id 分别关联订单、商品和卖家。支付和评价各通过 order_id 关联订单。这六条必备关联的缺失键和非空未匹配键均为 0。

| 补充属性 | 键缺失记录数 | 键非空但未匹配记录数 |
| --- | ---: | ---: |
| 商品到品类翻译 | 610 | 13 |
| 客户到代表坐标 | 0 | 279 |
| 卖家到代表坐标 | 0 | 42 |

这些补充属性允许覆盖缺口，分析时按相应键左关联。交易与履约指标将在分析层各自规定状态、时间和缺失处理口径。

第 22 份 Notebook 验证九表行数、字段格式、主键、必备关联和三项整数分合计。下一阶段以清单为输入生成并回读 Parquet，再按同一套字段和关联编写 MySQL 建表与装载流程。
