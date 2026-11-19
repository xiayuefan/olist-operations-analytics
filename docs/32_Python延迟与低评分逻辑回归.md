# 第 40 课 Python 延迟与低评分逻辑回归

Q22 用相同的客户州构成比较两组。Q23 把客户州和下单月份同时放进逻辑回归，在同州、同月的条件下描述延迟与低评分的关联。

从项目根目录的 PowerShell 运行脚本。验证环境使用项目 `.venv` 和 scikit-learn 1.3.2，脚本读取前面已生成的 Parquet。

```powershell
.\.venv\Scripts\python.exe .\src\13_delay_review_logistic.py
```

如果该环境提示缺少 `sklearn`，可用同一个解释器安装本课验证过的版本，再运行上面的命令。

```powershell
.\.venv\Scripts\python.exe -m pip install scikit-learn==1.3.2
```

## Q23 比较两个模型

两行使用同一批 **95,560 笔**可判断延迟且有有效评分的订单。因变量 `low_score` 表示最新评分是否为 1 星或 2 星。`delay_only` 只放入是否延迟，`state_and_month` 另外放入客户州和下单月份。州、月份都作为类别处理。模型使用 `penalty=None` 拟合无正则化的系数。[scikit-learn 1.3.2 逻辑回归文档](https://scikit-learn.org/1.3/modules/generated/sklearn.linear_model.LogisticRegression.html)

| 字段 | 含义 |
| --- | --- |
| `late_odds_ratio` | 延迟订单相对按时或提前订单的低评分优势比（OR）。`state_and_month` 比较同州同月下的优势。 |
| `on_time_low_score_pct` | 把同一批订单的延迟标记设为 0 时，模型拟合概率的平均值，单位为百分比。 |
| `late_low_score_pct` | 把同一批订单的延迟标记设为 1 时，模型拟合概率的平均值，单位为百分比。 |
| `low_score_gap_pp` | 两个平均拟合概率的差值，单位为百分点。 |

如果低评分概率为 (p)，低评分优势是 (p/(1-p))。逻辑回归把延迟系数取指数，得到两组的优势之比。比如概率从 20% 到 40% 时，概率变成 2 倍，优势比却是 ((0.40/0.60)/(0.20/0.80) approx 2.67)。[Penn State 逻辑回归与优势比](https://online.stat.psu.edu/stat504/Lesson06)

模型中的州和月份可以解释一部分订单构成差异。两组平均拟合概率用同一批订单的州和月份计算。结果描述历史样本中的统计关联，品类和卖家等因素仍可能影响关联。

实际运行已核对两组订单数与 Q22 一致。仅含延迟的模型用四格表核对优势比。加入州和月份的模型用另一种求解器复核优势比和平均拟合概率差值。

## 我的理解

1. 两个模型的 `late_odds_ratio` 分别是多少？用「同州、同月」和「低评分优势」解释第二行的 OR。
2. 加入州和月份后，`low_score_gap_pp` 变大还是变小？这列的单位是什么？
