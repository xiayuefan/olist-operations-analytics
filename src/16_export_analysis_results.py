"""Export portfolio tables from verified Parquet; no database credentials needed.

These are independently computed Pandas results. They do not claim that SQL or
Power BI Desktop was executed in this export run.
"""
import importlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from reviews_cleaning import select_latest_reviews


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/processed/mysql_input_v1'
BI = ROOT / 'data/processed/powerbi_v1'
OUTPUT = ROOT / 'reports/analysis_v1'
START, END = pd.Timestamp('2017-01-01'), pd.Timestamp('2018-09-01')


def read(name, folder=SOURCE):
    return pd.read_parquet(folder / (name + '.parquet'))


def export():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    inventory = []

    def save(name, frame, note):
        frame.to_csv(OUTPUT / (name + '.csv'), index=False, encoding='utf-8-sig')
        inventory.append({'file': name + '.csv', 'rows': len(frame), 'meaning': note})

    orders, items, customers = read('orders'), read('order_items'), read('customers')
    valid_window = orders.order_purchase_timestamp.ge(START) & orders.order_purchase_timestamp.lt(END)
    window = orders.loc[valid_window].copy()
    delivered = window.loc[window.order_status.eq('delivered')].copy()
    amount = items.groupby('order_id').agg(goods_cents=('price_cents','sum'), freight_cents=('freight_cents','sum'))
    delivered = delivered.join(amount, on='order_id').merge(
        customers[['customer_id','customer_unique_id','customer_state']], on='customer_id', validate='one_to_one')
    insights = read('order_insights', BI)
    delivered = delivered.merge(insights, on='order_id', validate='one_to_one')
    delivered['purchase_month'] = delivered.order_purchase_timestamp.dt.strftime('%Y-%m')
    delivered['low'] = delivered.latest_review_score.isin([1,2])

    status = orders.order_status.value_counts().rename_axis('order_status').reset_index(name='order_count')
    status['order_share_pct'] = 100*status.order_count/status.order_count.sum()
    save('order_status', status, '全历史订单状态分布，Q01')
    monthly = window.assign(purchase_month=window.order_purchase_timestamp.dt.strftime('%Y-%m')).groupby('purchase_month').agg(
        placed_orders=('order_id','size'))
    monthly = monthly.join(delivered.groupby('purchase_month').agg(delivered_orders=('order_id','size'),
        goods_cents=('goods_cents','sum'),freight_cents=('freight_cents','sum')))
    monthly['delivered_pct'] = 100*monthly.delivered_orders/monthly.placed_orders
    monthly['goods_gmv_brl'] = monthly.goods_cents/100
    monthly['goods_aov_brl'] = monthly.goods_cents/monthly.delivered_orders/100
    monthly['goods_gmv_mom_pct'] = 100*monthly.goods_cents.pct_change()
    monthly['order_count_mom_pct'] = 100*monthly.delivered_orders.pct_change()
    monthly['goods_aov_mom_pct'] = 100*monthly.goods_aov_brl.pct_change()
    previous = monthly.shift(1)
    effects = [pd.NA]
    for index in range(1,len(monthly)):
        cents = (Decimal(int(monthly.delivered_orders.iloc[index])-int(previous.delivered_orders.iloc[index]))
                 * Decimal(int(previous.goods_cents.iloc[index])) / Decimal(int(previous.delivered_orders.iloc[index])))
        effects.append(int(cents.quantize(Decimal('1'), rounding=ROUND_HALF_UP)))
    monthly['order_effect_cents'] = pd.array(effects, dtype='Int64')
    monthly['aov_effect_cents'] = monthly.goods_cents.diff().astype('Int64')-monthly.order_effect_cents
    save('monthly_business',monthly.reset_index(),'主窗口已交付经营、环比与成交额拆解，Q04–Q06')

    categories = read('product_categories',BI)
    sales = items.merge(delivered[['order_id','purchase_month','customer_state']],on='order_id',validate='many_to_one').merge(
        categories,on='product_id',validate='many_to_one')
    for key, name in [('category_label','category'), ('customer_state','state')]:
        summary = sales.groupby(key,as_index=False).agg(item_lines=('order_id','size'),orders=('order_id','nunique'),
            goods_cents=('price_cents','sum'),freight_cents=('freight_cents','sum')).sort_values(['goods_cents',key],ascending=[False,True])
        summary['gmv_rank'] = np.arange(1,len(summary)+1)
        summary['gmv_share_pct'] = 100*summary.goods_cents/summary.goods_cents.sum()
        summary['cumulative_gmv_pct'] = summary.gmv_share_pct.cumsum()
        summary['goods_aov_brl'] = summary.goods_cents/summary.orders/100
        summary['freight_over_goods_pct'] = 100*summary.freight_cents/summary.goods_cents
        save(name+'_structure',summary,'主窗口结构和贡献，含缺失品类；品类订单数跨组不可加，Q07/Q09/Q34')
        changes=sales.loc[sales.purchase_month.isin(['2017-10','2017-11'])].pivot_table(
            index=key,columns='purchase_month',values='price_cents',aggfunc='sum',fill_value=0).reset_index()
        changes['change_cents']=changes['2017-11']-changes['2017-10']
        changes['net_change_share_pct']=100*changes.change_cents/changes.change_cents.sum()
        save(name+'_november_growth',changes.sort_values(['change_cents',key],ascending=[False,True]),'11 月相对 10 月商品金额增量，Q08/Q10')

    save('monthly_purchase',read('monthly_purchase',BI),'窗口内首次与后续已交付购买订单，Q12')
    save('customer_cohort',read('customer_cohort',BI),'30/60/90 天复购客户和观察期资格，未成熟留空，Q14')
    save('customer_rfm_segments',read('customer_rfm',BI),'基准日 2018-09-01，两阶段 F/R/M 分群，Q16')
    customer_rfm = delivered.groupby('customer_unique_id',as_index=False).agg(last_purchase=('order_purchase_timestamp','max'),
        frequency=('order_id','size'),priced_orders=('goods_cents','count'),goods_cents=('goods_cents','sum'))
    customer_rfm['recency_days']=(END-customer_rfm.last_purchase.dt.normalize()).dt.days
    customer_rfm['goods_cents']=customer_rfm.goods_cents.where(customer_rfm.priced_orders.eq(customer_rfm.frequency)).astype('Int64')
    save('customer_rfm',customer_rfm,'客户级 R/F/M 明细，Q15')
    frequency=customer_rfm.groupby('frequency',as_index=False).agg(customers=('customer_unique_id','size'))
    frequency['delivered_orders']=frequency.frequency*frequency.customers
    save('customer_frequency',frequency,'窗口内已交付订单的客户频次分布，Q11')

    valid=delivered.loc[delivered.delay_band_order.notna()].copy()
    bands=valid.groupby(['delay_band_order','delay_band'],as_index=False).agg(orders=('order_id','size'),
        rated_orders=('latest_review_score','count'),low_score_orders=('low','sum'))
    bands['low_score_rate_pct']=100*bands.low_score_orders/bands.rated_orders
    bands['review_coverage_pct']=100*bands.rated_orders/bands.orders
    save('delay_bands_and_reviews',bands,'有效延迟订单分档及评价覆盖，Q18/Q19')
    stages=[]
    for stage, column in [('approval','approval_days'),('handoff','handoff_days'),('transit','transit_days')]:
        values=delivered[column].dropna()
        stages.append({'stage':stage,'eligible_orders':len(values),'p50_days':values.quantile(.5),'p90_days':values.quantile(.9)})
    save('stage_duration',pd.DataFrame(stages),'阶段有效样本和线性插值分位数，Q32')
    reviews=delivered.latest_review_score.value_counts(dropna=False).rename_axis('latest_review_score').reset_index(name='orders')
    save('latest_score_distribution',reviews,'全部已交付订单评分分布，包含无评分订单，Q33')
    valid['is_late']=valid.delay_band_order.ge(2)
    state=valid.groupby(['customer_state','is_late'],as_index=False).agg(orders=('order_id','size'),
        rated_orders=('latest_review_score','count'),low_score_orders=('low','sum'))
    n=state.rated_orders
    proportion=state.low_score_orders/n
    z=1.96
    center=(proportion+z*z/(2*n))/(1+z*z/n)
    radius=z*np.sqrt(proportion*(1-proportion)/n+z*z/(4*n*n))/(1+z*z/n)
    state['low_score_rate_pct']=100*proportion
    state['wilson_lower_pct']=100*(center-radius)
    state['wilson_upper_pct']=100*(center+radius)
    save('state_delay_review_wilson',state,'州内分组比较和 Wilson 95% 区间，Q20/Q21')
    shared=state.groupby('customer_state').filter(lambda g: len(g)==2 and g.rated_orders.gt(0).all()).copy()
    weights=shared.groupby('customer_state').rated_orders.sum()/shared.rated_orders.sum()
    shared['weight']=shared.customer_state.map(weights)
    shared['contribution']=shared.weight*shared.low_score_orders/shared.rated_orders
    standardized=shared.groupby('is_late',as_index=False).agg(rated_orders=('rated_orders','sum'),
        low_score_orders=('low_score_orders','sum'),standardized_rate=('contribution','sum'))
    standardized['observed_rate']=standardized.low_score_orders/standardized.rated_orders
    save('state_standardization',standardized,'两组共用合并样本州权重，比例未乘 100，Q22')

    seller=read('seller_snapshot',BI)
    save('seller_snapshot',seller,'单卖家样本卖家指标、固定簇、规则和 PCA 坐标，Q26–Q31')
    save('seller_candidates',seller.loc[seller.rule_candidate].sort_values(
        ['low_score_orders','late_orders','seller_id'],ascending=[False,False,True]),'全量 102 位候选卖家，Q27')
    qualified=seller.loc[seller.pc1.notna()]
    profile=qualified.groupby('cluster_label',as_index=False).agg(sellers=('seller_id','size'),
        single_seller_orders=('single_seller_orders','sum'),median_orders=('single_seller_orders','median'),
        valid_delay_orders=('valid_delay_orders','sum'),late_orders=('late_orders','sum'),
        rated_orders=('rated_orders','sum'),low_score_orders=('low_score_orders','sum'),rule_candidates=('rule_candidate','sum'))
    profile['late_rate_pct']=100*profile.late_orders/profile.valid_delay_orders
    profile['low_score_rate_pct']=100*profile.low_score_orders/profile.rated_orders
    profile['rule_candidate_share_pct']=100*profile.rule_candidates/profile.sellers
    save('seller_cluster_profiles',profile,'簇级订单加权比率和规则重合，Q29/Q31')
    cluster_module=importlib.import_module('14_seller_clustering')
    seller_metrics=cluster_module.build_seller_metrics()
    _,scaled=cluster_module.prepare_cluster_features(seller_metrics)
    diagnostics,_=cluster_module.compare_cluster_counts(scaled)
    save('seller_k_diagnostics',diagnostics,'K=2–5，种子间稳定性和轮廓系数，Q29')

    regression=importlib.import_module('13_delay_review_logistic')
    sample=regression.add_main_category(regression.load_analysis_sample())
    controls=pd.get_dummies(sample[['customer_state','purchase_month']],drop_first=True,dtype=int)
    first=sample[['is_late']]
    adjusted=pd.concat([first,controls],axis=1)
    with_category=pd.concat([adjusted,pd.get_dummies(sample[['main_category']],drop_first=True,dtype=int)],axis=1)
    with threadpool_limits(limits=1):
        models=[regression.summarize_model(name,features,sample.low_score) for name,features in [
            ('delay_only',first),('state_and_month',adjusted),('state_month_and_category',with_category)]]
    save('delay_review_logistic',pd.DataFrame(models),'同样本无惩罚逻辑回归，优势比和平均拟合概率差，Q23/Q24')
    assert len(delivered)==96211 and int(sales.price_cents.sum())==1318102713
    assert int(bands.orders.sum())==96203 and int(seller.rule_candidate.sum())==102
    assert int(monthly.loc['2017-11','order_effect_cents'])==40692813
    assert int(customer_rfm.frequency.sum())==96211
    save('result_index',pd.DataFrame(inventory),'本次导出文件清单和计算口径')
    metadata={'engine':'Pandas / scikit-learn; independent recomputation, not MySQL execution',
              'window_start':'2017-01-01','window_end_exclusive':'2018-09-01','delivered_orders':len(delivered),
              'valid_delay_orders':len(valid),'goods_cents':int(sales.price_cents.sum()),'tables':len(inventory)}
    (OUTPUT/'run_info.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(metadata,ensure_ascii=False,indent=2))


if __name__=='__main__':
    export()
