# 第 24 课 MySQL 建表与核对

用上一课的入库清单建一个项目数据库 `olist_operations_analytics`。这一步的验收结果为 9 张表、9 个主键、6 条外键。首次建表后，各表的实际行数为 0。下一课从 Parquet 装载数据。

## 1. 登录本机 MySQL

在 PowerShell 终端运行以下两行。如果你平时使用另一个 MySQL 账号，把 `root` 换成你的账号。MySQL 会在终端提示输入密码。[MySQL 连接选项](https://dev.mysql.com/doc/refman/8.0/en/connection-options.html)

```powershell
Set-Location -LiteralPath 'D:\数据分析\olist-operations-analytics'
& 'D:\MySQL\MySQL Server 8.0\bin\mysql.exe' --host=127.0.0.1 --port=3306 --user=root --password --default-character-set=utf8mb4
```

## 2. 执行建表和核对脚本

看到 `mysql>` 后，依次执行以下两个客户端命令。[MySQL 客户端命令](https://dev.mysql.com/doc/refman/8.0/en/mysql-commands.html)

```text
source sql/01_create_schema.sql
source sql/02_check_schema.sql
```

如果你已在 SQL 编辑器中登录本机数据库，可以依次打开这两份 SQL，分别执行整个文件。

`01_create_schema.sql` 由入库清单生成，先建立客户、商品、卖家等被引用的表，再建立订单及其明细。外键关联的两侧使用一致的字段类型和字符排序规则。[MySQL 外键要求](https://dev.mysql.com/doc/refman/8.0/en/create-table-foreign-keys.html)

`02_check_schema.sql` 的第一个结果表应为：

| table_count | primary_key_count | foreign_key_count |
| ---: | ---: | ---: |
| 9 | 9 | 6 |

后面的结果依次列出主键列、外键关系、三个字段的类型与可空性，以及九张表的实际行数。

## 3. 看懂一个组合主键和一条外键

在 `order_items` 中，`order_id + order_item_id` 组合标识订单里的某条明细。同一个 `order_id` 可以在明细表出现多次。明细的 `order_id` 同时是外键，每个非空订单键都需要在 `orders` 中有对应记录。

品类翻译和地理坐标作为补充属性，通过查询时的左关联获取。允许缺失译名和代表坐标的记录照常保留。

把第一个核对结果发来，再用自己的话解释为什么 `order_items` 的 `order_id` 可以是外键，而该表的主键需要两列。

建表脚本已在独立的 MySQL 8.0.37 实例验证，104 个字段的类型和可空性、九个主键与六条外键均与入库清单一致。可从项目根目录运行 `python .\src\11_generate_mysql_schema.py` 按清单重新生成建表 SQL。
