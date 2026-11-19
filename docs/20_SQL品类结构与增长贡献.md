# 第 28 课 SQL 品类结构与增长贡献

上一课拆出 2017 年 11 月商品成交额的订单量贡献和客单价贡献。本课从商品明细进一步定位成交额集中在哪些品类，以及哪些品类贡献了当月增量。

在 `mysql>` 执行以下命令。

```text
source D:/数据分析/olist-operations-analytics/sql/06_category_contribution.sql
```

## Q07 按品类看成交额结构

沿用 2017-01 至 2018-08 窗口和已交付订单口径。从 `order_items` 按 `product_id` 找到商品品类，每条商品明细的 `price_cents` 只计入一个品类组。

先按原始品类聚合，再左关联英文翻译。原始品类缺失集中在 `(missing)` 组，有原始品类但没有译名时展示原始名称。`category_mapping` 区分这两种情况。

`ROW_NUMBER()` 按成交额从高到低编号。`SUM(...) OVER (...)` 从第一位累计到当前位，除以窗口总成交额得到累计占比。`crosses_80_pct = 1` 标记累计占比第一次达到 80% 的那一行。 [MySQL 窗口帧](https://dev.mysql.com/doc/refman/8.0/en/window-functions-frames.html)

`category_orders` 是品类内去重订单数。一笔订单若买了两个品类，会分别进入这两个品类的订单数。全平台订单数仍从订单粒度单独计算。

## Q08 按品类定位 11 月增量

在 2017 年 10 月和 11 月的已交付明细中，`SUM(CASE WHEN ... THEN price_cents ELSE 0 END)` 在同一品类组内分别算两个月的金额。这个写法会保留只在其中一个月出现的品类。

`change_brl` 是该品类 11 月金额减 10 月金额。`net_change_share_pct` 用该品类的变化金额除以全平台净变化。负值表示该品类抵消了一部分增量。

两条查询已在独立 MySQL 8.0.37 运行并与 Pandas 逐行核对。Q07 有 **74 个品类组**，成交额合计 **13,181,027.13 BRL**。Q08 有 **68 个品类组**，各品类变化相加为 **339,517.72 BRL**，和上一课 11 月的净变化一致。

请发来两项结果。Q07 找到 `crosses_80_pct = 1` 的那一行。Q08 看排在第一位的品类及其 `change_brl`，用一句话说明它给 11 月的成交额增加了多少。
