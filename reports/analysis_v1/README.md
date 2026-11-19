# 分析结果快照

运行 `python src/16_export_analysis_results.py` 可从已核对的 Parquet 独立重算本目录。计算使用 Pandas/scikit-learn，导出日期为 2026-11-19。没有把独立重算写成本次 MySQL 或 Power BI 执行记录。

| 结果 | 文件 |
| --- | --- |
| 全历史状态与窗口月度经营 | [状态](order_status.csv)、[月度经营与拆解](monthly_business.csv) |
| 品类结构和 11 月增长 | [结构](category_structure.csv)、[增量](category_november_growth.csv) |
| 客户州结构、运费负担和增长 | [结构](state_structure.csv)、[增量](state_november_growth.csv) |
| 客户购买频次和月度结构 | [频次](customer_frequency.csv)、[首次与后续购买](monthly_purchase.csv) |
| 客户级 RFM 与分层 | [客户级明细](customer_rfm.csv)、[分组](customer_rfm_segments.csv) |
| 固定随访窗口复购 | [30/60/90 天 Cohort](customer_cohort.csv) |
| 履约时长与分档 | [阶段样本及 P50/P90](stage_duration.csv)、[延迟档位及评价](delay_bands_and_reviews.csv) |
| 评分覆盖与州内比较 | [最新评分结构](latest_score_distribution.csv)、[州比较和 Wilson 区间](state_delay_review_wilson.csv) |
| 标准化与回归关联 | [共用州权重](state_standardization.csv)、[三种回归模型](delay_review_logistic.csv) |
| 卖家指标和治理名单 | [卖家快照](seller_snapshot.csv)、[102 位候选](seller_candidates.csv) |
| 卖家聚类诊断及画像 | [K 值诊断](seller_k_diagnostics.csv)、[簇画像](seller_cluster_profiles.csv) |

完整文件和行数见 [result_index.csv](result_index.csv)。金额列 `_cents` 是整数分，`_brl` 是 BRL，比例列 `_pct` 用 0–100 标度。`state_standardization.csv` 的 `observed_rate` 和 `standardized_rate` 使用 0–1 比例，`low_score_gap_pp` 使用百分点。缺失 Cohort 结果保留空值。

主分析窗口为 2017-01-01（含）至 2018-09-01（不含），商品成交额只汇总最终已交付订单的商品金额。延迟分母为 96,203 笔可判断订单，评分、客户、卖家的样本要求分别判断。主窗口共 96,211 笔已交付订单、商品成交额 13,181,027.13 BRL。

本次重算验证了订单和金额总额、五档订单数、客户 F 合计、11 月订单量贡献以及卖家候选人数。完整项目的 27 个清洗单元测试通过。历史质量报告仍保留各自运行时的版本元数据，不把所有阶段改写成同一次运行。
