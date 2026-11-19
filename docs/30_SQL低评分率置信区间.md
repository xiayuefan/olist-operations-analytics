# 第 38 课 SQL 低评分率置信区间

RO 的延迟组有 4 笔低评分、7 笔有效评分，观察到的低评分率是 57.14%。SP 的延迟组低评分率是 54.35%，来自 1,783 笔有效评分。两个比例接近，估计精度可以相差很大。

在 `mysql>` 中运行下面的命令。

```text
source D:/数据分析/olist-operations-analytics/sql/16_delay_review_confidence_intervals.sql
```

## Q21 给每组低评分率加上 95% 置信区间

继续使用 Q20 的订单样本和低评分口径。每行代表一个客户州的一种交付状态。`on_time_or_early` 表示按时或提前，`late` 表示延迟。`low_score_orders` 除以 `rated_orders` 得到 `low_score_rate_pct` 所展示的比例。

`ci_lower_pct` 和 `ci_upper_pct` 是 Wilson 95% 置信区间的两端。这个方法用低评分订单数和有效评分订单数计算比例区间。比如观测到 0 笔低评分时，点估计为 0%，但样本很小的组仍可能有较高的区间上限。[NIST 比例置信区间公式](https://itl.nist.gov/div898/handbook/prc/section2/prc241.htm)

区间是在把组内评分结果视为独立二项观测的前提下计算的。95% 指在相同条件下反复抽样并构造区间，长期约 95% 的区间会覆盖目标比例。区间越宽，说明在这个模型下估计越不精确。[NIST 置信区间定义](https://itl.nist.gov/div898/handbook/prc/section1/prc14.htm)

查询已在独立 MySQL 8.0.37 中运行，54 行均与 Python 重算结果一致。`rated_orders` 合计 95,560 笔，与 Q20 一致。

## 我的理解

1. 找到 SP 和 RO 的 `late` 行。它们的置信区间各是多少？哪个更宽？结合 `rated_orders` 解释。
2. 找到 AP 的 `late` 行。这个组的点估计是多少？区间上限又是多少？结合样本量解释这两个数字。
