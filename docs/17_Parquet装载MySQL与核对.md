# 第 25 课 Parquet 装载 MySQL 与核对

这一步把九张已回读核对的 Parquet 表写入 MySQL 数据库 `olist_operations_analytics`。目标库使用上一课创建的九张空表。

## 1. 在本机终端运行装载脚本

保留原来的 `mysql>` 窗口，在另一个 PowerShell 终端运行下面两行。脚本默认连接本机 3306 端口、使用 `root` 账号，并在终端提示输入密码。其他账号可在命令末尾加上 `--user 账号名`。

```powershell
Set-Location -LiteralPath 'D:\数据分析\olist-operations-analytics'
.\.venv\Scripts\python.exe .\src\12_load_mysql.py
```

项目虚拟环境使用 PyMySQL 1.1.2 连接数据库。依赖清单见 requirements-mysql.txt。 [PyMySQL 1.1.2](https://pypi.org/project/PyMySQL/1.1.2/)

## 2. 看懂写入与提交

脚本先核对 Parquet 校验值、字段、主键和关联，再检查目标库的表结构与空表状态。写入顺序沿用清单，客户、商品和卖家先写入，订单商品、支付和评价等子表随后写入。

写入进度显示「等待提交」时，数据还在事务中。脚本核对九张表的行数、三项整数分金额及重量标记后才提交。事务中若遇到写入或核对错误，已写入的行会回滚。目标表已有数据时，脚本会在写入前停止。 [MySQL 事务语句](https://dev.mysql.com/doc/refman/8.0/en/commit.html)

成功时，终端显示「提交成功」以及 9 张表、569,778 行。这个总行数是九张表的行数相加。订单表应为 99,441 行。

## 3. 在 MySQL 中独立核对

提交后回到原来的 `mysql>` 窗口，执行以下客户端命令。使用 SQL 编辑器时，可以打开并执行同一份文件。 [MySQL 客户端命令](https://dev.mysql.com/doc/refman/8.0/en/mysql-commands.html)

```text
source D:/数据分析/olist-operations-analytics/sql/03_check_loaded_data.sql
```

检查九张表的 `row_difference` 和三项金额的 `difference_cents`，预期全部为 0。最后一项应显示 2，表示重量及零重量标记都为空的商品仍有两条。

请发来行数与金额核对结果，再用一句话解释为什么应先装订单表、再装订单商品明细。

装载流程已在独立的 MySQL 8.0.37 实例验证，包括全量装载、外键失败回滚、重复装载拦截与三项金额核对。
