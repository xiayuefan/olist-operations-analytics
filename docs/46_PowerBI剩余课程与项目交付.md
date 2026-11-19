# Olist 剩余课程｜Power BI 到作品集

这份讲义一次给出第 54–62 课。直接继续做，不用每课等批改。第 53 课的瀑布图也可以和第 54 课一起完成。每一课都有验收点，末尾附对照答案。[第 53 课瀑布图](45_PowerBI成交额增长瀑布图.md)

| 课程 | 要完成的内容 | 验收产物 |
| --- | --- | --- |
| [54](#lesson54) | 补模型、整理经营总览与增长拆解 | 第 1–2 页 |
| [55](#lesson55) | 品类结构、州级增量、运费负担 | 第 3 页 |
| [56](#lesson56) | 履约延迟与各阶段耗时 | 第 4 页 |
| [57](#lesson57) | 评价覆盖、低评分与延迟关联 | 第 5 页 |
| [58](#lesson58) | 卖家聚类与规则跟进 | 第 6 页 |
| [59](#lesson59) | 两阶段 RFM | 第 7 页 |
| [60](#lesson60) | 月度复购与 Cohort | 第 8 页 |
| [61](#lesson61) | Python、MySQL、Power BI 三方验收 | 核对表和报表截图 |
| [62](#lesson62) | 业务建议、作品集、简历与答辩 | 作品说明和讲稿 |

<a id="lesson54"></a>

## 第 54 课 补齐模型，整理经营总览和增长拆解

先保存现有 `.pbix` 的副本。以下统一用你报表里的 `orders`、`order_items` 和 `Calendar`。新表及列按讲义命名，度量值在「新建度量值」逐个粘贴，同名度量沿用上一课。金额和天数用小数显示两位，计数用整数，比率设为百分比两位。公式里的 `DIVIDE` 直接返回比例，不再乘 100。

在项目根目录运行。脚本以原来入库用的 Parquet 为输入，生成六张分析表并逐一回读。已有 `mysql_input_v1` 时可以直接运行，无需连接 MySQL。

```powershell
.\.venv\Scripts\python.exe .\src\15_export_powerbi.py
```

如果提示缺少 scikit-learn，用同一个虚拟环境安装 `scikit-learn==1.3.2`，再重跑。若还没有源 Parquet，先运行 `src/10_export_parquet.py`，再用第 23 份 Notebook 检查导出结果。六张新表和 `controls.json` 写在 `data/processed/powerbi_v1/`。实际文件见 [数据准备脚本](../src/15_export_powerbi.py)；导入方法见 [Microsoft Learn · Parquet 连接器](https://learn.microsoft.com/en-us/power-query/connectors/parquet)。

| Parquet | 报表名称或用法 | 每行代表 |
| --- | --- | --- |
| `powerbi_v1/order_insights` | `OrderInsights`，在 Power Query 中合并进 `orders` | 一个订单 |
| `powerbi_v1/product_categories` | `ProductCategories` | 一个商品 |
| `mysql_input_v1/customers` | `Customers`，只保留 `customer_id`、`customer_state` | 一条客户订单身份记录 |
| `powerbi_v1/seller_snapshot` | `SellerSnapshot` | 一个有单卖家已交付订单的卖家 |
| `powerbi_v1/customer_rfm` | `CustomerRFM` | 一个 F、R、M 分组组合 |
| `powerbi_v1/monthly_purchase` | `MonthlyPurchase` | 一个下单月 |
| `powerbi_v1/customer_cohort` | `CustomerCohort` | 一个首购月与随访天数组合 |

1. 在 Power Query 导入 `OrderInsights`。选 `orders` 查询，点「合并查询」，两边选文本型 `order_id`，连接类型选「左外部」。展开 `latest_review_score`、`delay_band`、`delay_band_order`、`approval_days`、`handoff_days`，取消自动加列名前缀。将评分和档位序号设为整数，档位名设为文本，两个耗时设为小数。订单原有的 `transit_days` 用小数，`delivery_delay_days` 用整数。缺失保留为空。右键 `OrderInsights` 取消「启用加载」，让它作为合并的中间查询。
2. 加载 `Customers` 与 `ProductCategories`，其余四张快照可在对应课再导入。每次导入检查自动关系。下表列出的四条都是活动关系，从 `1` 端单向筛到 `*` 端。`SellerSnapshot`、`CustomerRFM`、`MonthlyPurchase` 和 `CustomerCohort` 保持独立；只用各自的字段控制图表。第 53 课的瀑布图步骤表也保持独立。[Microsoft Learn · 管理关系](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-create-and-manage-relationships)

| `1` 端 | `*` 端 |
| --- | --- |
| `Calendar[Date]` | `orders[purchase_date]` |
| `Customers[customer_id]` | `orders[customer_id]` |
| `orders[order_id]` | `order_items[order_id]` |
| `ProductCategories[product_id]` | `order_items[product_id]` |

在 `orders` 下添加以下度量。这里用分档序号判断是否有可信的延迟天数，评分用每单最新有效评分。低评分率的分母独立于延迟率。

```dax
可判断延迟订单数 =
CALCULATE ( [已交付订单数], KEEPFILTERS ( orders[delay_band_order] >= 1 ) )
```

```dax
延迟订单数 =
CALCULATE ( [已交付订单数], KEEPFILTERS ( orders[delay_band_order] >= 2 ) )
```

```dax
延迟率 = DIVIDE ( COALESCE ( [延迟订单数], 0 ), [可判断延迟订单数] )
```

```dax
有有效评分订单数 =
CALCULATE ( COUNT ( orders[latest_review_score] ), orders[order_status] = "delivered" )
```

```dax
低评分订单数 =
CALCULATE (
    [已交付订单数],
    KEEPFILTERS ( orders[latest_review_score] IN { 1, 2 } )
)
```

```dax
低评分率 = DIVIDE ( COALESCE ( [低评分订单数], 0 ), [有有效评分订单数] )
```

| 页面 | 放什么 | 筛选怎么用 |
| --- | --- | --- |
| 1 经营总览 | 下单、已交付、交付率、商品成交额、商品客单价、延迟率和低评分率卡片，保留一张月度概览折线 | 日期范围 `2017-01-01` 至 `2018-08-31`，默认月份清空 |
| 2 增长拆解 | 月度趋势、两项贡献、上月金额、环比、瀑布图 | 日期范围沿用前一页，单选 `2017-11` 看瀑布；用「编辑交互」把月份切片器对全窗口趋势图的影响设为「无」 |

复制已有图表到「增长拆解」，再按表收拾「经营总览」。如果要实现趋势折线一直可见，将单月切片器与趋势折线之间的交互关掉，日期范围切片器仍作用于两者。月份切片器保留在本页，勿同步到固定快照页。[Microsoft Learn · 切片器与交互](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-slicers)

**验收**　清空经营总览月份，金额为 13,181,027.13 BRL，已交付订单 96,211 笔。增长页 `2017-11` 的瀑布图总计是 987,765.37 BRL。把月份换成 `2017-10`，瀑布改变而全窗口趋势仍保持。

<a id="lesson55"></a>

## 第 55 课 品类与地域

新建第 3 页「品类与地域」。品类销量用明细粒度，客户州订单数用订单粒度，两部分各放一个表格。使用 `Calendar[Date]` 把页面限定在经营窗口，新增 `Calendar[YearMonth]` 月份切片器。

```dax
已交付运费（BRL） =
DIVIDE (
    CALCULATE ( SUM ( order_items[freight_cents] ), orders[order_status] = "delivered" ),
    100
)
```

```dax
运费占商品金额比 = DIVIDE ( [已交付运费（BRL）], [商品成交额（BRL）] )
```

```dax
品类成交额占比 =
DIVIDE (
    [商品成交额（BRL）],
    CALCULATE ( [商品成交额（BRL）], ALLSELECTED ( ProductCategories[category_label] ) )
)
```

```dax
客户州成交额占比 =
DIVIDE (
    [商品成交额（BRL）],
    CALCULATE ( [商品成交额（BRL）], ALLSELECTED ( Customers[customer_state] ) )
)
```

```dax
分组成交额月变动（BRL） =
// 先在整个品类和客户范围判断两个月可否比较，再回到当前分组取金额。
VAR CanCompare =
    NOT ISBLANK (
        CALCULATE (
            [商品成交额变动（BRL）],
            REMOVEFILTERS ( ProductCategories ),
            REMOVEFILTERS ( Customers )
        )
    )
VAR CurrentAmount = [商品成交额（BRL）]
VAR PreviousAmount = [上月商品成交额（BRL）]
RETURN
    IF (
        CanCompare && NOT ( ISBLANK ( CurrentAmount ) && ISBLANK ( PreviousAmount ) ),
        COALESCE ( CurrentAmount, 0 ) - COALESCE ( PreviousAmount, 0 )
    )
```

| 图表 | 字段配置 |
| --- | --- |
| 品类表及条形图 | `ProductCategories[category_label]`，商品成交额、品类成交额占比、有商品明细的已交付订单数、分组成交额月变动；保留 `(missing)` 组。图按成交额降序，可只显示前十，完整表保留所有品类。 |
| 客户州表 | `Customers[customer_state]`，已交付订单数、商品成交额、客户州成交额占比、商品客单价、已交付运费、运费占商品金额比、分组成交额月变动。 |

`ALLSELECTED` 用当前选择的品类或州当分母，所以缩小选择后，占比会重新计算。同一笔订单可能跨品类，品类内订单数可以各计一次。州表是一单一个客户州。品类维度沿单向关系只筛到商品明细，品类图如果需要控制州表，请先明确想展示的是州的品类成交额还是该品类的下单笔数。本课在「编辑交互」关闭品类图对州表的作用，保留日期对两者的作用。[Microsoft Learn · ALLSELECTED](https://learn.microsoft.com/en-us/dax/allselected-function-dax)

**验收**　清空月份，在 MySQL Q07 核对品类成交额累计到第 18 位首次达到 80%，在 Q09 看 SP 的订单份额与成交额份额。再选 `2017-11`，将两张表按月变动降序，与 Q08、Q10 核对排首位的品类和州。看「运费占商品金额比」时要说清楚分母是商品金额；若想看运费占商品加运费的比例，需要另算一个指标。

<a id="lesson56"></a>

## 第 56 课 履约时效

新建第 4 页「履约时效」。放已交付、可判断延迟、延迟订单、延迟率四张卡；另放各档订单数的柱状图和按州展示各阶段耗时的表格。复制日期、月份切片器。对 `orders[delay_band]` 用「按列排序 → delay_band_order」，在图的视觉筛选里排除空白档。

各阶段的有效样本可以不同。审批是下单到批准，交承运商是批准到承运商接收，运输是承运商接收到客户签收。三者按经过秒数换算为天，延迟却用实际与预计的自然日差。把三个阶段分别做 P50、P90，并在表中显示用于计算的笔数；筛空值让分位数只看实际时长。[Microsoft Learn · PERCENTILEX.INC](https://learn.microsoft.com/en-us/dax/percentilex-inc-function-dax)

```dax
无法判断延迟订单数 =
IF (
    NOT ISBLANK ( [已交付订单数] ),
    [已交付订单数] - COALESCE ( [可判断延迟订单数], 0 )
)
```

```dax
审批有效订单数 = COUNT ( orders[approval_days] )
```

```dax
审批 P50（天） =
IF (
    [审批有效订单数] > 0,
    MEDIANX ( FILTER ( orders, NOT ISBLANK ( orders[approval_days] ) ), orders[approval_days] )
)
```

```dax
审批 P90（天） =
IF (
    [审批有效订单数] > 0,
    PERCENTILEX.INC ( FILTER ( orders, NOT ISBLANK ( orders[approval_days] ) ), orders[approval_days], 0.9 )
)
```

| 再建三条度量的组名 | 把审批公式中的 `approval_days` 换成 |
| --- | --- |
| `交承运商有效订单数`、`交承运商 P50（天）`、`交承运商 P90（天）` | `handoff_days` |
| `运输有效订单数`、`运输 P50（天）`、`运输 P90（天）` | `transit_days` |

替换公式时也替换 `IF` 中引用的有效订单数。三个有效订单数和六个分位数都放入表格，行用 `Customers[customer_state]`。可在页面上方加一个州切片器，卡片、分档图与州表会一起变化。

**验收**　全窗口 96,203 笔可判断延迟，6,531 笔延迟，延迟率 6.79%，无法判断 8 笔。五档相加是 96,203，延迟超过 7 天的两档相加是 2,860 笔。用附录对照三组时长的样本数和 P50/P90。读州级 P90 时顺手看该行的样本数。

<a id="lesson57"></a>

## 第 57 课 评价体验

新建第 5 页「评价体验」。复制履约页的日期与月份切片器，默认日期保持 `2017-01-01` 至 `2018-08-31`，月份清空。评分柱状图的类别轴用 `orders[latest_review_score]` 的 1–5 分，值用 `[有有效评分订单数]`。另用一张表按 `orders[delay_band]` 比较延迟与评分，单列可判断延迟订单数、有效评分数、评价覆盖率、低评分率及区间。延迟分档表过滤掉空白档位，整体评分柱状图仍包括所有已交付订单里的有效评分。用「编辑交互」关闭评分柱状图对分档表的筛选，否则点击 1 星会让分档表只看 1 星。

```dax
延迟样本评价覆盖率 =
DIVIDE (
    COALESCE (
        CALCULATE ( [有有效评分订单数], KEEPFILTERS ( orders[delay_band_order] >= 1 ) ),
        0
    ),
    [可判断延迟订单数]
)
```

在分档表上，每一行由档位提供筛选，`[低评分率]` 的分母就是该档有效评分订单数。为了按州比较「延迟」与「按时或提前」，建矩阵，行取 `Customers[customer_state]`，列取 `orders[delay_band]`、值放低评分率和有效评分数；再加一张独立的州比较表，用下面两个度量合并所有延迟档。

```dax
按时或提前组低评分率 =
CALCULATE ( [低评分率], KEEPFILTERS ( orders[delay_band_order] = 1 ) )
```

```dax
延迟组低评分率 =
CALCULATE ( [低评分率], KEEPFILTERS ( orders[delay_band_order] >= 2 ) )
```

```dax
延迟与按时低评差（百分点） =
VAR LateRate = [延迟组低评分率]
VAR OnTimeRate = [按时或提前组低评分率]
RETURN
    IF ( NOT ISBLANK ( LateRate ) && NOT ISBLANK ( OnTimeRate ), 100 * ( LateRate - OnTimeRate ) )
```

第三项设成普通小数两位，单位在名称写「百分点」。在分档表添加下面两条 Wilson 区间度量，或先在 MySQL Q21 对照州级区间，再把它作为页面旁注。

```dax
低评 Wilson 下限 =
VAR N = [有有效评分订单数]
VAR P = [低评分率]
VAR Z = 1.96
VAR Z2 = Z * Z
RETURN
    IF (
        N > 0,
        DIVIDE ( P + Z2 / ( 2 * N ) - Z * SQRT ( P * ( 1 - P ) / N + Z2 / ( 4 * N * N ) ), 1 + Z2 / N )
    )
```

新增 `低评 Wilson 上限`，复制公式并把分子中 `- Z * SQRT` 换为 `+ Z * SQRT`。上下限都设成百分比。Q21 的 SP、RO 延迟组区间需把该州的四个延迟档合并成一个筛选范围才能对照。

**验收**　全窗口按时或提前为 9.25% 低评，延迟 15 天及以上为 78.32%。展示 69.07 **个百分点**的档位差距。再查旧课 Q22–Q24，分别解释原始比较、统一州权重以及加入州、月、主品类后得到的是哪一种关联；这些结果是固定窗口的专题证据，不能当作当前切片器下实时回归结果。[分层标准化](31_SQL按州标准化低评分率.md) · [主品类回归](33_Python加入主品类的延迟回归.md)

<a id="lesson58"></a>

## 第 58 课 卖家分层与治理

新建第 6 页，导入 `SellerSnapshot`。顶部注明「2017-01 至 2018-08 下单的单卖家已交付订单；聚类和候选身份按全窗口冻结」。筛选字段只用 `seller_state`、`cluster_label`。其中 `seller_state` 是卖家所在州，前面用的是客户所在州。

```dax
参与聚类卖家数 = COUNT ( SellerSnapshot[pc1] )
```

```dax
建议核查卖家数 =
COALESCE (
    CALCULATE ( COUNTROWS ( SellerSnapshot ), KEEPFILTERS ( SellerSnapshot[rule_candidate] = TRUE () ) ),
    0
)
```

```dax
卖家延迟率 = DIVIDE ( SUM ( SellerSnapshot[late_orders] ), SUM ( SellerSnapshot[valid_delay_orders] ) )
```

```dax
卖家低评分率 = DIVIDE ( SUM ( SellerSnapshot[low_score_orders] ), SUM ( SellerSnapshot[rated_orders] ) )
```

```dax
单卖家延迟基线 = CALCULATE ( [卖家延迟率], REMOVEFILTERS ( SellerSnapshot ) )
```

```dax
单卖家低评基线 = CALCULATE ( [卖家低评分率], REMOVEFILTERS ( SellerSnapshot ) )
```

| 图表 | 字段配置 |
| --- | --- |
| 卡片 | 参与聚类卖家数、建议核查卖家数、两条固定全样本基线 |
| PCA 散点图 | X=`pc1`，Y=`pc2`，图例=`cluster_label`，按点分组的「值」=`seller_id`；`pc1` 非空。若轴字段必须汇总，可选平均值，此时每个卖家只占一行。提示信息放订单数和两个比率。[Microsoft Learn · 散点图](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-scatter) |
| 簇汇总表 | `cluster_label`、参与聚类卖家数、建议核查卖家数、两个加权比率；此表去掉「未达到样本门槛」 |
| 跟进表 | `seller_id`、州、簇、`single_seller_orders`、`valid_delay_orders`、`rated_orders`、`late_orders`、`low_score_orders` 和两个比率；视觉筛选 `rule_candidate=True`。按低评分笔数降序，并列时看延迟笔数以及卖家 ID，和 Q27 对照。 |

规则看两种样本都是否达到 50 笔，而且两个比率是否均高于全体单卖家基线。列表按受影响订单笔数排序。聚类用于寻找共同特征，PCA 只是展示三个聚类特征的二维投影。过滤一个簇会改变页面样本，但不会重新训练聚类或改写候选资格。多卖家订单不在当前归因样本中。[Q27 规则](35_SQL卖家优先跟进清单.md) · [Q28 敏感性](36_SQL多卖家订单敏感性分析.md) · [Q31 规则对照](39_Python卖家聚类与跟进规则对照.md)

**验收**　默认看到 408 位参与聚类、102 位入选。三个簇分别入选 5、72、25 位。若只跟进簇 1 的 94 位，会多纳入 22 位未入选者、漏掉其他两簇的 30 位入选者。PCA 两轴累计解释约 85.21% 的变异。

<a id="lesson59"></a>

## 第 59 课 客户分群

新建第 7 页，导入 `CustomerRFM`。页面注明下单窗口和固定基准日 `2018-09-01`。每个客户在 RFM 计算中只进一个分组。这里的 `one_time` 是窗口内只买一次，`repeat` 是窗口内有至少两笔已交付订单，身份用 `customer_unique_id`。R 以最近一次下单距基准的天数划分，M 是该客户商品金额，先分 F 再按各组自己的离散 P75 切分。

```dax
RFM 客户数 = SUM ( CustomerRFM[customer_count] )
```

```dax
RFM 已交付订单数 = SUM ( CustomerRFM[delivered_orders] )
```

```dax
RFM 商品成交额（BRL） = DIVIDE ( SUM ( CustomerRFM[goods_cents] ), 100 )
```

```dax
RFM 客户人均商品金额（BRL） =
DIVIDE (
    [RFM 商品成交额（BRL）],
    CALCULATE ( [RFM 客户数], KEEPFILTERS ( CustomerRFM[monetary_group] <> "unknown_m" ) )
)
```

```dax
RFM 组内 P75（BRL） = DIVIDE ( SELECTEDVALUE ( CustomerRFM[m_cutoff_cents] ), 100 )
```

矩阵行用 `frequency_group`、`recency_group`，列用 `monetary_group`，值放客户数和商品成交额。另用 F 组条形图比较订单数或金额，卡片显示客户总数。可用 `frequency_group` 和 `recency_group` 切片；查看 P75 时放在按 F 分行的表中。两个组都选中且门槛不同，P75 卡片应留空，不能把两个门槛平均后当作总体 P75。商品金额未知的客户可参加 R/F 统计，按已知 M 客户算人均金额。

**验收**　90,315 位单次购买客户和 2,789 位窗口内复购客户合计 93,104 位，归集 96,211 笔已交付订单。两组 P75 分别为 149.90 和 304.48 BRL。150 BRL 落在两组的不同 M 档。[Q15–Q16 口径](26_SQL客户RFM两阶段分层.md)

<a id="lesson60"></a>

## 第 60 课 复购与 Cohort

新建第 8 页，导入 `MonthlyPurchase`、`CustomerCohort`。左侧展示某下单月的首次、后续购买订单，右侧展示某首购月的完整窗口复购率。一个看订单，一个看客户。首次都指窗口内观察到的首次已交付购买，历史截止在 `2018-09-01` 零点之前。

```dax
后续购买订单占比 = DIVIDE ( SUM ( MonthlyPurchase[repeat_orders] ), SUM ( MonthlyPurchase[delivered_orders] ) )
```

```dax
首购客户数 =
IF ( HASONEVALUE ( CustomerCohort[followup_days] ), SUM ( CustomerCohort[cohort_customers] ) )
```

```dax
随访完整客户数 =
IF ( HASONEVALUE ( CustomerCohort[followup_days] ), SUM ( CustomerCohort[eligible_customers] ) )
```

```dax
待成熟客户数 =
IF ( HASONEVALUE ( CustomerCohort[followup_days] ), SUM ( CustomerCohort[pending_customers] ) )
```

```dax
窗口内复购客户数 =
IF (
    HASONEVALUE ( CustomerCohort[followup_days] )
        && HASONEVALUE ( CustomerCohort[first_purchase_month] )
        && [首购客户数] > 0
        && [随访完整客户数] = [首购客户数],
    SUM ( CustomerCohort[repeat_customers] )
)
```

```dax
完整窗口复购率 = DIVIDE ( [窗口内复购客户数], [随访完整客户数] )
```

1. 用 `MonthlyPurchase[purchase_month]` 做轴，堆积柱放 `first_orders` 和 `repeat_orders`，另做折线展示后续购买订单占比。月文本按 `yyyy-MM` 升序。
2. Cohort 矩阵行用 `first_purchase_month`，列用整数 `followup_days`，值为完整窗口复购率。可给比率加背景色。打开行字段的「显示无数据的项」，或用旁边的明细表展示全套月份和期限；明细表附上首购客户数、随访完整客户数和待成熟客户数。关闭矩阵总计。不同期限共用同一客户，不能跨 30、60、90 天求总人数。
3. 为两块分别加本表的筛选器。想让左右同时筛同一个时间时，先想清楚左边是下单月，右边是首次购买月。同一个月份值指向不同事件，本课用两套独立筛选并标清含义。[Q14 窗口规则](24_SQL多窗口复购比较.md)

**验收**　`2017-11` 有 228 笔后续购买订单，占当月 7,289 笔已交付订单的 3.13%。`2018-05` 的 30、60、90 天复购人数是 67、87、105，分母均为 6,508 位。`2018-06` 的 90 天率留空，因为还有 5,563 位观察期未完整。完整窗口里观察到 0 人复购则应显示 0%。

<a id="lesson61"></a>

## 第 61 课 三方核对和报表体验验收

打开 [项目交付记录](47_项目交付核对与答辩.md)，逐行填 Power BI 的实际值。先以相同日期、状态和粒度核对 Python、MySQL、Power BI，再验证有操作时的表现。MySQL 明细入库控制可跑 `sql/03_check_loaded_data.sql`；按主题数值用记录表里标明的 Q 编号核对。若只核对到截图显示精度，金额请在表格中保留两位并查看未缩写的数字。

另跑 `sql/21_powerbi_delivery_checks.sql`。Q32 用排序和线性插值复核三个阶段的 P50/P90，Q33 补齐全部已交付订单的评分分布，Q34 比较各州的运费负担，Q35 从已入库的商品与支付明细核对全历史订单差额。Q35 中支付较高 367 笔、较低 209 笔、完全一致 98,089 笔、无法核对 776 笔。差额提示后续查证，无法单凭这两张表确定多收或少收的原因。项目现在有 30 个带编号的专题 SQL 查询，另有 5 个 Python 专题（Q23–Q24、Q29–Q31）。

| 操作 | 应看到的结果 |
| --- | --- |
| 总览清空月份，再单选 2017-11 | 全窗口与 11 月各自的订单、成交额和分母正确 |
| 增长页从 2017-11 切 2017-10，再选窗口首月 2017-01 | 单月瀑布变化，首月无可比上月，全窗口趋势仍显示 |
| 调整品类或州 | 各页只影响预期的图；解释品类订单数为何不能跨品类相加 |
| 清空履约和评价页月份，然后选择样本少的州 | 比率和分母同时变化；无资格的比率留空 |
| 卖家切簇或州，客户页切 F 或 R | 当前展示样本变化，聚类身份、平台基线、RFM 门槛保持定义 |
| Cohort 对比 2018-05 和 2018-06 的 90 天格子 | 一个能比较，一个显示观察期不足；未成熟格子保留空值 |
| 文件关闭并重开 | 8 页都存在，默认筛选可读；如需刷新，项目路径下源文件都可访问 |

完成后保存 `powerbi/Olist经营与履约分析.pbix`，该目录可自行新建。留一张模型关系截图、一套八页截图，以及至少一张「选中月份后」的交互截图。标题标注窗口和指标单位，检查长英文品类名不会挡住金额。报表仍可能包含底层数据，公开时优先用必要的汇总图和方法说明。

<a id="lesson62"></a>

## 第 62 课 作品集、简历与答辩

用 [项目交付记录与讲稿](47_项目交付核对与答辩.md) 完成作品收尾。作品先回答业务问题，再展示图和方法，最后写建议怎么验证。至少保留经营、履约、卖家三条建议。客户分群和 Cohort 作为可追加的运营验证方向。

1. 在作品首页写 150–250 字，说明分析窗口、九张来源表、交付了哪些产物，并挑三条能回到图表和查询的发现。
2. 每条建议写明「发现 → 下一步动作 → 衡量指标、对照与观察期」。示例建议和指标字典在交付记录中，可以直接引用后按实际报表调整。
3. 对照验收表，把已完成的工作写进简历。第一次讲五分钟，听众问起订单和商品明细的区别时，能举例说明怎样避免重复金额。再讲一遍指标分母、未成熟 Cohort 和延迟关联的限制。

## 对照答案

金额为 BRL，比例均保留两位。Python 已回读输入，按项目口径重算下列对照值。Power BI 中的度量运行、图表交互和文件保存仍需在你的 Desktop 中完成。

| 项目 | 对照值 |
| --- | --- |
| 经营全窗口 | 下单 99,092；已交付 96,211；交付率 97.09%；商品成交额 13,181,027.13；商品客单价 137.00；运费 2,192,092.88 |
| 2017-11 | 下单 7,544；已交付 7,289；交付率 96.62%；商品成交额 987,765.37；商品客单价 135.51；环比 52.37% |
| 2017-10 瀑布 | 上月 607,399.67；订单量贡献 +48,006.53；客单价贡献 −7,158.55；总计 648,247.65 |
| 2017-11 瀑布 | 上月 648,247.65；订单量贡献 +406,928.13；客单价贡献 −67,410.41；总计 987,765.37 |
| 品类与客户州 | 74 个品类组；全窗口第 18 位首次达到 80%；11 月 `bed_bath_table` 增加 41,949.93，SP 增加 130,986.10；分别按品类、州加总皆为 +339,517.72 |
| 审批、交承运商、运输 | 有效样本分别 96,197、94,845、96,018；P50 分别 0.01、1.84、7.11 天；P90 分别 1.44、5.99、18.92 天 |
| 延迟 | 五档订单数依次为 89,672、1,869、1,802、1,478、1,382；超过 7 天为 2,860。延迟率 6.79% |
| 评价 | 全部已交付中 95,568 笔有有效评分，12,229 笔为低评；可判断延迟的子样本有 95,560 笔评分。五档低评率依次 9.25%、32.14%、67.68%、80.15%、78.32% |
| 评价分层 | 可判断延迟样本中，延迟组与按时或提前组的低评率差为 53.17 个百分点；统一州权重后为 50.46 个百分点 |
| 卖家 | 有单卖家已交付订单的卖家 2,925 位；簇 0/1/2 分别 233/94/81 位；规则入选 5/72/25 位 |
| 客户 RFM | 93,104 位客户，单次 90,315，复购 2,789；M 组内 P75 为 149.90 和 304.48 |
| Cohort | `2018-05` 30、60、90 天率分别 1.03%、1.34%、1.61%；`2018-06` 90 天分母资格 316／5,879，未成熟率留空 |
