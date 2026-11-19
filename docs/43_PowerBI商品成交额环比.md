# 第 51 课 Power BI 商品成交额环比

在现有模型中新增两项度量，让 Power BI 按月算出上月商品成交额和环比增长率。沿用 2017 年 1 月至 2018 年 8 月的分析窗口和已交付商品成交额口径，与 MySQL 的 Q05 对照。

## 添加度量值

在 `orders` 下逐条新建度量值。第一个公式先用当前一行的日期确定月份，再在 `CALCULATE` 中换成上月的日期范围。`ALL ( 'Calendar' )` 让日期表的原有筛选退出这次计算，因此即使月份切片器只选了 11 月，度量值仍可取到 10 月的金额。[Microsoft Learn · CALCULATE](https://learn.microsoft.com/zh-cn/dax/calculate-function-dax) · [ALL](https://learn.microsoft.com/zh-cn/dax/all-function-dax)

```dax
上月商品成交额（BRL） =
IF (
    HASONEVALUE ( 'Calendar'[YearMonth] ),#只允许单选一个年月，多选直接返回空白
    VAR LastVisibleDate = MAX ( 'Calendar'[Date] )
    VAR CurrentMonthStart = EOMONTH ( LastVisibleDate, -1 ) + 1#月初（因为选了当月最大的那一个日期，减一个月变成上个月最大的那个日期，然后加一天变成这个月月初的那一天）
    VAR PreviousMonthStart = EOMONTH ( LastVisibleDate, -2 ) + 1#同理，这个是上个月月初
    VAR IsFullMonth =
        COUNTROWS ( VALUES ( 'Calendar'[Date] ) ) = DAY ( EOMONTH ( LastVisibleDate, 0 ) )
    RETURN
        IF (
            IsFullMonth && PreviousMonthStart >= DATE ( 2017, 1, 1 ),
            CALCULATE (
                [商品成交额（BRL）],
                FILTER (
                    ALL ( 'Calendar' ),
                    'Calendar'[Date] >= PreviousMonthStart#大于等于上月第一天
                        && 'Calendar'[Date] < CurrentMonthStart#小于本月第一天
                )
            )
        )
)
```

公式先确认只有一个月份，再用 `IsFullMonth` 检查它的天数，避免把半个月的金额与上月整月相比。2017 年 1 月是分析窗口的第一个月，上月金额和环比都留空。[Microsoft Learn · EOMONTH](https://learn.microsoft.com/zh-cn/dax/eomonth-function-dax) · [HASONEVALUE](https://learn.microsoft.com/zh-cn/dax/hasonevalue-function-dax)

```dax
商品成交额环比 =
VAR PreviousAmount = [上月商品成交额（BRL）]
VAR CurrentAmount = [商品成交额（BRL）]
RETURN
    IF (
        NOT ISBLANK ( CurrentAmount ),
        DIVIDE ( CurrentAmount - PreviousAmount, PreviousAmount )
    )
```

把「商品成交额环比」的格式设为百分比，保留两位小数。两项成交额保留两位小数。[Microsoft Learn · DIVIDE](https://learn.microsoft.com/zh-cn/dax/divide-function-dax)

## 在报表中核对

1. 在「经营总览」添加一个表格视觉对象，放入 `Calendar[YearMonth]`、`[商品成交额（BRL）]`、`[上月商品成交额（BRL）]` 和 `[商品成交额环比]`。按 `YearMonth` 升序。
2. 把日期范围设为 2017-01-01 至 2018-08-31，并清空月份切片器。检查 2017-01 的上月金额和环比是否留空，再与下面的两行对照。
3. 在月份切片器选 `2017-11`。表格只显示 11 月这一行，上月金额应仍是 10 月的 648,247.65 BRL。

| 月份 | 商品成交额（BRL） | 上月商品成交额（BRL） | 商品成交额环比 |
| --- | ---: | ---: | ---: |
| 2017-10 | 648,247.65 | 607,399.67 | 6.73% |
| 2017-11 | 987,765.37 | 648,247.65 | 52.37% |

对照值已用本地 Parquet 重算。DAX 和切片器的实际运行结果在 Power BI Desktop 中核对。

## 我的理解

1. 只选 `2017-11` 后，上月金额和环比各是多少？环比用哪一笔金额作分母？
2. 清空月份切片器后，为什么 2017-01 可以有成交额，但上月金额和环比都留空？
