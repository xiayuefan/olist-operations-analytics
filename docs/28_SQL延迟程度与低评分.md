# 第 36 课 SQL 延迟程度与低评分

沿用 Q18 的五个延迟档和 96,203 笔可判断延迟的订单。用每笔订单最新一次有效评价的评分衡量客户体验，把 1 星或 2 星定义为低评分。

在 `mysql>` 中运行以下命令。

```text
source D:/数据分析/olist-operations-analytics/sql/14_delay_review_association.sql
```

## Q19 比较不同延迟档的评价表现

1. `MAX(review_answer_timestamp)` 先找每单的最新提交时间，再连接评价明细取对应评分。`HAVING COUNT(*) = 1` 确保最新时间只对应一条记录。提交时间缺失、早于创建日期或最新时间并列时，该单的最新评分视为无法确定。当前数据中这三种情况的数量均为 0。
2. 用 `LEFT JOIN` 把订单与最新评分相连。无有效评分的订单仍计入 `order_count`。每档订单数应与 Q18 一致。
3. 评价覆盖率的分母是该档全部订单，低评分率的分母是该档有有效评分的订单。某档没有有效评分时，低评分率为 `NULL`。

| 字段 | 含义 |
| --- | --- |
| `order_count` | 该档的可判断延迟订单数 |
| `rated_orders` | 其中有有效评分的订单数 |
| `orders_without_valid_review` | 其中缺少有效评分的订单数 |
| `low_score_orders` | 其中最新有效评分为 1 星或 2 星的订单数 |
| `review_coverage_pct` | `rated_orders` ÷ `order_count` × 100 |
| `low_score_rate_pct` | `low_score_orders` ÷ `rated_orders` × 100 |

这张表描述延迟程度与低评分在历史订单中的关联。读低评分率时也要看每档的 `rated_orders`，这样能知道比例来自多少笔订单。

查询已在独立 MySQL 8.0.37 中运行。五档的订单数均与 Q18 一致，评分计数和比率也与 Pandas 逐行一致。

## 我的理解

1. 「按时或提前」和「延迟 15 天及以上」两档的低评分率各是多少？用表中两个百分比相减，差多少个百分点？
2. 为什么低评分率要除以 `rated_orders`？如果除以 `order_count`，无有效评分订单会怎样影响这个比例？
