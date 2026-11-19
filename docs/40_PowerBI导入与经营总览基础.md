# 第 48 课 Power BI 导入与经营总览基础

用前面已经核对的两张 Parquet 建立模型，完成三项经营指标。用日期筛选验证订单数和商品金额能一起变化。

## 导入订单和商品明细

在 Power BI Desktop 选择「获取数据 → Parquet」。分别导入下面两个本地文件，选择「转换数据」进入 Power Query 编辑器。[Microsoft Learn · Parquet 连接器](https://learn.microsoft.com/en-us/power-query/connectors/parquet)

```text
D:\数据分析\olist-operations-analytics\data\processed\mysql_input_v1\orders.parquet
D:\数据分析\olist-operations-analytics\data\processed\mysql_input_v1\order_items.parquet
```

| 查询名称 | 每行代表 | 核对字段 | 整表行数 |
| --- | --- | --- | ---: |
| `Orders` | 一笔订单 | `order_id` 为文本，`order_purchase_timestamp` 为日期/时间 | 99,441 |
| `OrderItems` | 一条商品明细 | `order_id` 为文本，`price_cents` 为整数 | 112,650 |

在 `Orders` 选「添加列 → 自定义列」，列名填 `purchase_date`，公式填 `Date.From([order_purchase_timestamp])`，将新列类型设为「日期」。原来的时间戳继续保留，供后续分析使用。[Microsoft Learn · Date.From](https://learn.microsoft.com/en-us/powerquery-m/date-from)

点击「关闭并应用」。成功导入后选「建模 → 新建表」，粘贴以下 DAX。日期表覆盖源数据所在的 2016 至 2018 三个完整自然年，经营比较窗口在报表中筛选。

```dax
Calendar =
ADDCOLUMNS (
    CALENDAR ( DATE ( 2016, 1, 1 ), DATE ( 2018, 12, 31 ) ),
    "YearMonth", FORMAT ( [Date], "yyyy-MM" )
)
```

选 `Calendar` 表并用 `[Date]` 将它标记为日期表。在模型视图建立或核对以下两条**活动关系**。两条均为一对多、单向筛选，箭头从 `1` 端指向 `*` 端。检查已自动生成的关系，保留符合下表的两条。[Microsoft Learn · 日期表](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-date-tables) · [Microsoft Learn · 模型关系](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-create-and-manage-relationships)

| `1` 端 | `*` 端 |
| --- | --- |
| `Calendar[Date]` | `Orders[purchase_date]` |
| `Orders[order_id]` | `OrderItems[order_id]` |

因此筛选 `Calendar[YearMonth]` 会先缩小订单范围，再沿 `order_id` 缩小商品明细范围。

## 添加三项度量并核对结果

在 `Orders` 下用「新建度量值」逐条添加以下公式。`CALCULATE` 中的状态条件作用在 `Orders` 上，并通过关系传给 `OrderItems`。商品成交额用已交付订单的商品金额，整数分求和后除以 100 得到 BRL。[Microsoft Learn · CALCULATE](https://learn.microsoft.com/en-us/dax/calculate-function-dax)

```dax
下单订单数 = COUNTROWS ( Orders )
```

```dax
已交付订单数 =
CALCULATE ( [下单订单数], Orders[order_status] = "delivered" )
```

```dax
商品成交额（BRL） =
DIVIDE (
    CALCULATE ( SUM ( OrderItems[price_cents] ), Orders[order_status] = "delivered" ),
    100
)
```

在报表中新建一页「经营总览」。放三张卡片，每张使用一个度量。前两张显示整数，成交额保留两位小数。如卡片自动缩写数字，将显示单位设为「无」。添加 `Calendar[Date]` 的日期范围切片器并设置 2017-01-01 至 2018-08-31。再建一个 `Calendar[YearMonth]` 切片器，用它切换月份。

| 筛选范围 | 下单订单数 | 已交付订单数 | 商品成交额（BRL） |
| --- | ---: | ---: | ---: |
| 2017-01-01 至 2018-08-31，月份切片器清空 | 99,092 | 96,211 | 13,181,027.13 |
| 同一日期范围，月份切片器选 `2017-11` | 7,544 | 7,289 | 987,765.37 |

上述对照值已从本地 Parquet 重新计算。模型关系、卡片和切片器需在 Power BI Desktop 中运行，确认与你看到的实际结果一致。把报告保存到自己的项目目录。

## 我的理解

1. 在模型视图中，两条关系各自的 `1` 端和 `*` 端是什么？为什么 `Orders` 可以在一条关系中是 `*` 端，在另一条关系中是 `1` 端？
2. 选 `2017-11` 后，发来三张卡片的值。为什么筛选 `Calendar` 会改变 `OrderItems` 的金额？
