# 第 52 课 Power BI 成交额增长拆解

11 月的商品成交额比 10 月高，商品客单价却更低。本课沿用 MySQL Q06 的算法，把成交额变动拆成订单量贡献和客单价贡献。订单量指有商品明细的已交付订单数，与客单价的分母一致。

## 添加四项度量值

在 `orders` 下逐条新建度量值。先用第 51 课的 `[上月商品成交额（BRL）]` 判断当前月份是否可比较，再在同一段上月日期范围内计算订单数。`CALCULATE` 只为这次计算替换日历筛选。[Microsoft Learn · CALCULATE](https://learn.microsoft.com/zh-cn/dax/calculate-function-dax)

```dax
上月有商品明细的已交付订单数 =
IF (
    NOT ISBLANK ( [上月商品成交额（BRL）] ),
    VAR LastVisibleDate = MAX ( 'Calendar'[Date] )
    VAR CurrentMonthStart = EOMONTH ( LastVisibleDate, -1 ) + 1
    VAR PreviousMonthStart = EOMONTH ( LastVisibleDate, -2 ) + 1
    RETURN
        CALCULATE (
            [有商品明细的已交付订单数],
            FILTER (
                ALL ( 'Calendar' ),
                'Calendar'[Date] >= PreviousMonthStart
                    && 'Calendar'[Date] < CurrentMonthStart
            )
        )
)
```

```dax
商品成交额变动（BRL） =
IF (
    [有商品明细的已交付订单数] > 0
        && [上月有商品明细的已交付订单数] > 0,
    ROUND ( [商品成交额（BRL）] - [上月商品成交额（BRL）], 2 )
)
```

订单量贡献等于订单数变动乘以上月客单价。上月客单价直接用上月成交额除以上月订单数，计算时保留原来的精度，最后把贡献四舍五入到分。

```dax
订单量贡献（BRL） =
VAR ChangeAmount = [商品成交额变动（BRL）]
VAR PreviousOrders = [上月有商品明细的已交付订单数]
VAR PreviousAOV = DIVIDE ( [上月商品成交额（BRL）], PreviousOrders )
RETURN
    IF (
        NOT ISBLANK ( ChangeAmount ),
        ROUND ( ( [有商品明细的已交付订单数] - PreviousOrders ) * PreviousAOV, 2 )
    )
```

客单价贡献等于成交额变动减去订单量贡献。按 Q06 的舍入规则，用这个差额保证两项贡献加起来与成交额变动精确对齐到分。舍入前，这一项也可以理解为客单价变动乘以本月订单数。

```dax
客单价贡献（BRL） =
VAR ChangeAmount = [商品成交额变动（BRL）]
RETURN
    IF (
        NOT ISBLANK ( ChangeAmount ),
        ROUND ( ChangeAmount - [订单量贡献（BRL）], 2 )
    )
```

## 在表格中核对

在第 51 课的环比表格中加上「商品成交额变动（BRL）」「订单量贡献（BRL）」「客单价贡献（BRL）」。保持日历范围为 2017-01-01 至 2018-08-31，月份切片器选 `2017-11`。三项金额都显示两位小数。

| 月份 | 商品成交额变动（BRL） | 订单量贡献（BRL） | 客单价贡献（BRL） |
| --- | ---: | ---: | ---: |
| 2017-11 | 339,517.72 | 406,928.13 | −67,410.41 |

对照值已用本地 Parquet 按 Q06 的公式重算。DAX 和报表的运行结果在 Power BI Desktop 中核对。

## 我的理解

1. 11 月的两项贡献分别是多少？哪一项推高了成交额，哪一项抵消了部分增量？
2. 为什么订单量贡献采用上月客单价？结合公式，用一句话解释这项贡献的含义。
