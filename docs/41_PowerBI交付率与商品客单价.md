# 第 49 课 Power BI 交付率与商品客单价

在「经营总览」加入交付率和商品客单价。两项度量都会随日期切片器重新计算。沿用第 48 课的日期范围和两条模型关系。下面的公式使用当前报表里的 `orders` 和 `order_items` 表名。如果你的商品明细表叫 `OrderItems`，把公式里的 `order_items` 换成该名称。

## 添加度量值

在 `orders` 下用「新建度量值」逐条添加下面三个公式。`DIVIDE` 在分母为 0 或空值时默认返回空值。[Microsoft Learn · DIVIDE](https://learn.microsoft.com/zh-cn/dax/divide-function-dax)

```dax
交付率 =
DIVIDE ( [已交付订单数], [下单订单数] )
```

```dax
有商品明细的已交付订单数 =
CALCULATE (
    DISTINCTCOUNT ( order_items[order_id] ),
    orders[order_status] = "delivered"
)
```

```dax
商品客单价（BRL） =
DIVIDE ( [商品成交额（BRL）], [有商品明细的已交付订单数] )
```

客单价的分母沿用 MySQL Q04 的口径。一笔已交付订单有多条商品明细时，`DISTINCTCOUNT` 按订单 ID 计一次。在本次分析窗口内，每笔已交付订单都有商品明细，所以这个分母与已交付订单数相等。[Microsoft Learn · DISTINCTCOUNT](https://learn.microsoft.com/zh-cn/dax/distinctcount-function-dax)

## 加卡片并核对切片器

1. 在「经营总览」新增两张卡片，分别放入「交付率」和「商品客单价（BRL）」。在度量值格式中把交付率设为百分比、保留两位小数。DAX 公式返回的是比例，百分比格式会把 `0.9662` 显示为 `96.62%`。
2. 把商品客单价设为小数并保留两位小数。若卡片覆盖了度量格式，可以在视觉对象的「常规 → 数据格式」中选择对应度量值，调整小数位。[Microsoft Learn · 自定义格式字符串](https://learn.microsoft.com/zh-cn/power-bi/create-reports/desktop-custom-format-strings)
3. 确认日期滑块为 2017-01-01 至 2018-08-31。先在月份切片器选 `2017-11`，再清空月份切片器，对照两次的结果。

| 筛选范围 | 交付率 | 商品客单价（BRL） |
| --- | ---: | ---: |
| 2017-11 | 96.62% | 135.51 |
| 2017-01 至 2018-08 | 97.09% | 137.00 |

以上数值已用本地 Parquet 重算。卡片和 DAX 度量的实际运行结果在你的 Power BI Desktop 中核对。

## 我的理解

1. 选 2017-11 时，两张新卡片各显示多少？两个指标分别用什么作分母？
2. 清空月份切片器后，为什么整体交付率要用整个窗口的已交付订单数除以下单订单数？如果每个月的下单订单数不同，直接平均月交付率会怎样给各月分配权重？
