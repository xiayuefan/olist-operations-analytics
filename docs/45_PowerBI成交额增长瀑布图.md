# 第 53 课 Power BI 成交额增长瀑布图

在「经营总览」页添加一张瀑布图。从上月商品成交额出发，依次加上订单量贡献和客单价贡献，最后读出本月商品成交额。

## 建立步骤表

在 Power BI Desktop 选「建模 → 新建表」，粘贴下面的 DAX。序号决定柱子的顺序，文字用作图上的标签。这张表只提供三个步骤，和 `Calendar`、`orders` 等业务表之间无需建立关系。[Microsoft Learn · DATATABLE](https://learn.microsoft.com/zh-cn/dax/datatable-function-dax)

```dax
成交额拆解步骤 =
DATATABLE (
    "步骤序号", INTEGER,
    "步骤", STRING,
    {
        { 1, "上月成交额" },
        { 2, "订单量贡献" },
        { 3, "客单价贡献" }
    }
)
```

在报表视图的数据窗格中选中 `成交额拆解步骤[步骤]`，再选「列工具 → 按列排序 → 步骤序号」。这样标签按业务顺序排列。[Microsoft Learn · 按列排序](https://learn.microsoft.com/zh-cn/power-bi/create-reports/desktop-sort-by-column)

## 为每根柱子提供一个金额

在 `orders` 下新建度量值。每根柱子都有一个步骤，`SELECTEDVALUE` 取出该步骤的序号，`SWITCH` 再返回对应的金额。月份切片器照常筛选业务度量，即使步骤表没有关系也能更新图上的金额。[Microsoft Learn · SELECTEDVALUE](https://learn.microsoft.com/zh-cn/dax/selectedvalue-function-dax)

```dax
瀑布图金额（BRL） =
// 只有本月和上月可比较时才画图，沿用上一课的判断。
VAR ChangeAmount = [商品成交额变动（BRL）]
// 每根柱子只对应一个步骤序号。
VAR StepNumber = SELECTEDVALUE ( '成交额拆解步骤'[步骤序号] )
RETURN
    IF (
        NOT ISBLANK ( ChangeAmount ),
        SWITCH (
            StepNumber,
            1, [上月商品成交额（BRL）],
            2, [订单量贡献（BRL）],
            3, [客单价贡献（BRL）]
        )
    )
```

## 添加瀑布图并核对

1. 在「经营总览」页插入原生「瀑布图」。把 `成交额拆解步骤[步骤]` 放到「类别」，把 `[瀑布图金额（BRL）]` 放到「Y 轴」。「细目」留空。
2. 打开图右上角的 `…`，在排序菜单中选「步骤」和「升序」。最后一根「总计」由图表累加前三项生成，代表本月成交额。把本月成交额也放进步骤表，会让总计再加一次本月金额。[Microsoft Learn · 瀑布图](https://learn.microsoft.com/zh-cn/power-bi/visuals/power-bi-visualization-waterfall-charts)
3. 保持日期范围为 `2017-01-01` 至 `2018-08-31`，在月份切片器中只选 `2017-11`。如果轴上显示千或百万，把鼠标悬停在柱子上读金额，或用上一课的表格核对到分。最终总计应与同页的商品成交额卡片一致。

| 柱子 | 2017 年 11 月金额（BRL） |
| --- | ---: |
| 上月成交额 | 648,247.65 |
| 订单量贡献 | +406,928.13 |
| 客单价贡献 | −67,410.41 |
| 总计 | 987,765.37 |

清空月份切片器后，成交额卡片仍可显示整个窗口的金额。瀑布图只回答某个月相比上个月发生了什么，因此多个月份、首个完整月 `2017-01` 或只选到半个月时，度量值留空。

## 我的理解

1. 切到 `2017-10`，写出两项贡献和最后一根柱子的金额。最后一根柱子与商品成交额卡片一致吗？
2. 为什么步骤表只有三行，图上却可以出现四根柱子？
