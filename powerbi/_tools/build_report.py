"""Build an editable, native eight-page PBIP from the Olist course sources."""
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'powerbi' / 'Olist'
REPORT = OUT / 'Olist.Report'
MODEL = OUT / 'Olist.SemanticModel'
DATA = OUT / 'data'
SCHEMA = 'https://developer.microsoft.com/json-schemas/fabric/'
NAVY, TEAL, CORAL, GRAY = '#152D44', '#087E8B', '#D65D54', '#65798A'
PAGES = ['经营总览', '增长拆解', '品类与地域', '履约时效', '评价体验', '卖家分层与治理', '客户分群', '复购与 Cohort']
MEASURES = {}


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def uid(text):
    return hashlib.sha256(text.encode()).hexdigest()[:20]


def add_measure(name, expression, folder='经营', fmt=None):
    if fmt is None:
        fmt = '#,0.00' if ('BRL' in name or '（天）' in name or '百分点' in name) else (
            '0.00%' if any(word in name for word in ('率', '占比', '金额比', '基线', 'Wilson', '环比')) else '#,0')
    MEASURES[name] = {'name': name, 'expression': expression.strip(), 'formatString': fmt, 'displayFolder': folder}


def prepare_data():
    DATA.mkdir(parents=True, exist_ok=True)
    raw = ROOT / 'data/processed/mysql_input_v1'
    prepared = ROOT / 'data/processed/powerbi_v1'
    orders = pd.read_parquet(raw / 'orders.parquet')
    orders['purchase_date'] = orders['order_purchase_timestamp'].dt.normalize()
    insights = pd.read_parquet(prepared / 'order_insights.parquet')
    orders = orders.merge(insights, on='order_id', how='left', validate='one_to_one')
    needed = ['order_id', 'customer_id', 'order_status', 'purchase_date', 'order_purchase_timestamp',
              'is_valid_delay', 'delivery_delay_days', 'transit_days', 'latest_review_score',
              'delay_band', 'delay_band_order', 'approval_days', 'handoff_days']
    tables = {'orders': orders[needed],
              'order_items': pd.read_parquet(raw / 'order_items.parquet', columns=['order_id', 'order_item_id', 'product_id', 'price_cents', 'freight_cents']),
              'Customers': pd.read_parquet(raw / 'customers.parquet', columns=['customer_id', 'customer_state'])}
    for file, table in [('product_categories', 'ProductCategories'), ('seller_snapshot', 'SellerSnapshot'),
                        ('customer_rfm', 'CustomerRFM'), ('monthly_purchase', 'MonthlyPurchase'), ('customer_cohort', 'CustomerCohort')]:
        tables[table] = pd.read_parquet(prepared / f'{file}.parquet')
    dates = pd.date_range('2016-01-01', '2018-12-31')
    tables['Calendar'] = pd.DataFrame({'Date': dates, 'YearMonth': dates.strftime('%Y-%m'),
                                       '经营窗口': (dates >= '2017-01-01') & (dates < '2018-09-01')})
    tables['成交额拆解步骤'] = pd.DataFrame({'步骤序号': [1, 2, 3], '步骤': ['上月成交额', '订单量贡献', '客单价贡献']})
    tables['指标'] = pd.DataFrame({'说明': ['可在字段列表中选择度量，全部计数按指定粒度计算。']})
    for name, frame in tables.items():
        frame.to_parquet(DATA / f'{name}.parquet', index=False)
        pd.testing.assert_frame_equal(frame.reset_index(drop=True), pd.read_parquet(DATA / f'{name}.parquet'))
    return tables


def prepare_measures():
    # Use the exact course formulas, with display aliases normalised to the actual model.
    for path in sorted((ROOT / 'docs').glob('4[0-6]_*.md')):
        for dax in re.findall(r'```dax\s*\n(.*?)```', path.read_text(encoding='utf-8'), re.S):
            dax = '\n'.join(line.split('#')[0] for line in dax.splitlines())
            if '=' not in dax:
                continue
            name, expr = dax.split('=', 1)
            name = name.strip()
            if name in ('Calendar', '成交额拆解步骤'):
                continue
            expr = expr.replace('OrderItems', 'order_items').replace('Orders', 'orders')
            folder = '经营' if path.name[:2] < '46' else '专题'
            add_measure(name, expr, folder)
    for stage, column in [('交承运商', 'handoff_days'), ('运输', 'transit_days')]:
        add_measure(f'{stage}有效订单数', f'COUNT ( orders[{column}] )', '履约')
        for pct, operation in [('P50', f'MEDIANX ( FILTER ( orders, NOT ISBLANK ( orders[{column}] ) ), orders[{column}] )'),
                               ('P90', f'PERCENTILEX.INC ( FILTER ( orders, NOT ISBLANK ( orders[{column}] ) ), orders[{column}], 0.9 )')]:
            add_measure(f'{stage} {pct}（天）', f'IF ( [{stage}有效订单数] > 0, {operation} )', '履约')
    lower = MEASURES['低评 Wilson 下限']['expression']
    add_measure('低评 Wilson 上限', lower.replace('- Z * SQRT', '+ Z * SQRT'), '评价')
    for name, expr in {
        '卖家单卖家订单数': 'SUM ( SellerSnapshot[single_seller_orders] )',
        '卖家有效延迟订单数': 'SUM ( SellerSnapshot[valid_delay_orders] )',
        '卖家延迟订单数': 'SUM ( SellerSnapshot[late_orders] )',
        '卖家有评分订单数': 'SUM ( SellerSnapshot[rated_orders] )',
        '卖家低评分订单数': 'SUM ( SellerSnapshot[low_score_orders] )',
        'PCA 横坐标': 'AVERAGE ( SellerSnapshot[pc1] )',
        'PCA 纵坐标': 'AVERAGE ( SellerSnapshot[pc2] )',
        '窗口内首次购买订单数': 'SUM ( MonthlyPurchase[first_orders] )',
        '窗口内后续购买订单数': 'SUM ( MonthlyPurchase[repeat_orders] )',
        '客户月已交付订单数': 'SUM ( MonthlyPurchase[delivered_orders] )',
    }.items():
        add_measure(name, expr, '快照', '#,0.00' if name.startswith('PCA') else '#,0')


def build_model(tables):
    model_tables = []
    for name, frame in tables.items():
        columns = []
        for column, dtype in frame.dtypes.items():
            dtype = str(dtype)
            data_type = ('dateTime' if 'datetime' in dtype else 'boolean' if dtype in ('bool', 'boolean') else
                         'int64' if dtype.lower().startswith(('int', 'uint')) else 'double' if dtype.lower().startswith('float') else 'string')
            obj = {'name': column, 'dataType': data_type, 'sourceColumn': column, 'summarizeBy': 'none'}
            if data_type == 'dateTime':
                obj['formatString'] = 'yyyy-MM-dd' if column in ('purchase_date', 'Date') else 'yyyy-MM-dd HH:mm:ss'
            elif data_type == 'int64':
                obj['formatString'] = '#,0'
            if column in ('order_id', 'customer_id', 'product_id') or name == '指标':
                obj['isHidden'] = True
            if name == 'orders' and column == 'delay_band':
                obj['sortByColumn'] = 'delay_band_order'
            if name == '成交额拆解步骤' and column == '步骤':
                obj['sortByColumn'] = '步骤序号'
            columns.append(obj)
        query = ['let', f'    Source = Parquet.Document(File.Contents(DataRoot & "\\{name}.parquet"))', 'in', '    Source']
        table = {'name': name, 'columns': columns, 'partitions': [{'name': name, 'mode': 'import',
                      'source': {'type': 'm', 'expression': query}}]}
        if name == 'Calendar':
            table['columns'][0]['isKey'] = True
            table['annotations'] = [{'name': '__PBI_TimeIntelligenceEnabled', 'value': '0'}]
        if name == '指标':
            table['measures'] = list(MEASURES.values())
        model_tables.append(table)
    relations = [('orders', 'purchase_date', 'Calendar', 'Date'), ('orders', 'customer_id', 'Customers', 'customer_id'),
                 ('order_items', 'order_id', 'orders', 'order_id'), ('order_items', 'product_id', 'ProductCategories', 'product_id')]
    model = {'name': 'Olist', 'compatibilityLevel': 1567, 'model': {
        'culture': 'en-US', 'defaultPowerBIDataSourceVersion': 'powerBI_V3',
        'dataAccessOptions': {'legacyRedirects': True, 'returnErrorValuesAsNull': True},
        'sourceQueryCulture': 'en-US', 'tables': model_tables,
        'relationships': [{'name': uid('.'.join(rel)), 'fromTable': rel[0], 'fromColumn': rel[1],
                            'toTable': rel[2], 'toColumn': rel[3], 'fromCardinality': 'many', 'toCardinality': 'one',
                            'crossFilteringBehavior': 'oneDirection'} for rel in relations],
        'expressions': [{'name': 'DataRoot', 'kind': 'm', 'expression':
                         json.dumps(str(DATA), ensure_ascii=False).replace('\\\\', '\\') + ' meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'}],
        'annotations': [{'name': 'PBI_QueryOrder', 'value': json.dumps(list(tables), ensure_ascii=False)},
                        {'name': '__PBI_TimeIntelligenceEnabled', 'value': '0'}]}}
    write(MODEL / 'model.bim', model)
    write(MODEL / 'definition.pbism', {'$schema': SCHEMA + 'item/semanticModel/definitionProperties/1.0.0/schema.json',
                                      'version': '1.0', 'settings': {'qnaEnabled': False}})


def literal(value):
    val = 'true' if value is True else 'false' if value is False else (
        "'" + value.replace("'", "''") + "'" if isinstance(value, str) else str(value) + 'D')
    return {'expr': {'Literal': {'Value': val}}}


def props(**kw):
    return [{'properties': {key: literal(value) for key, value in kw.items()}}]


def color(hex):
    return {'solid': {'color': literal(hex)}}


def field(table, name):
    kind = 'Measure' if table == '指标' else 'Column'
    return {kind: {'Expression': {'SourceRef': {'Entity': table}}, 'Property': name}}


def projection(item):
    table, name = item
    return {'field': field(table, name), 'queryRef': table + '.' + name, 'nativeQueryRef': name}


def measure(name):
    if name not in MEASURES:
        raise KeyError(name)
    return ('指标', name)


def in_filter(table, column, values, name=None):
    values = [values] if not isinstance(values, list) else values
    return {'name': name or uid(table + column + str(values)), 'field': field(table, column), 'type': 'Categorical',
            'filter': {'Version': 2, 'From': [{'Name': 's', 'Entity': table, 'Type': 0}], 'Where': [{'Condition': {'In': {
                'Expressions': [{'Column': {'Expression': {'SourceRef': {'Source': 's'}}, 'Property': column}}],
                'Values': [[{'Literal': {'Value': literal(value)['expr']['Literal']['Value']}}] for value in values]
            }}}]}, 'howCreated': 'User'}


def report_objects(title=None, background=True):
    result = {'background': [{'properties': {'show': literal(background), 'color': color('#FFFFFF'), 'transparency': literal(0)}}],
              'border': props(show=False),
              'padding': props(top=12, bottom=12, left=14, right=14),
              'visualHeader': props(show=True)}
    if title:
        result['title'] = [{'properties': {'show': literal(True), 'text': literal(title), 'fontSize': literal(12),
                                            'fontColor': color(NAVY), 'fontFamily': literal('Segoe UI'), 'bold': literal(True)}}]
    return result


class Page:
    def __init__(self, number, subtitle, snapshot=False):
        self.number = number
        self.name = uid('Olist page ' + str(number))
        self.directory = REPORT / 'definition/pages' / self.name
        self.visuals = []
        self.interactions = []
        self.obj = {'$schema': SCHEMA + 'item/report/definition/page/2.0.0/schema.json', 'name': self.name,
                    'displayName': f'{number:02d} {PAGES[number-1]}', 'displayOption': 'FitToPage', 'width': 1440, 'height': 920,
                    'objects': {'background': [{'properties': {'color': color('#F3F6F8'), 'transparency': literal(0)}}]}}
        self.text(f'{number:02d}  {PAGES[number-1]}', 32, 24, 1320, 52, size=28, ink=NAVY, bold=True)
        self.text(subtitle, 34, 82, 1370, 40, size=11, ink=GRAY)
        self.text('OLIST / OPERATIONS INTELLIGENCE', 36, 875, 620, 25, size=9, ink=GRAY)
        self.text(('固定观察窗 2017.01–2018.08' if snapshot else '下单日期口径 · 2017.01–2018.08') + f'  /  {number:02d}—08',
                  920, 875, 480, 25, size=9, ink=GRAY)

    def visual(self, kind, title, roles, x, y, w, h, objects=None, filters=None, sort=None):
        name = uid(f'{self.number}-{len(self.visuals)}-{kind}')
        visual = {'visualType': kind, 'drillFilterOtherVisuals': True, 'visualContainerObjects': report_objects(title)}
        if roles:
            query = {'queryState': {key: {'projections': [projection(item) for item in items]} for key, items in roles.items()}}
            if sort:
                query['sortDefinition'] = {'sort': [{'field': field(*sort[0]), 'direction': sort[1]}], 'isDefaultSort': False}
            visual['query'] = query
        if objects:
            visual['objects'] = objects
        obj = {'$schema': SCHEMA + 'item/report/definition/visualContainer/2.3.0/schema.json', 'name': name,
               'position': {'x': x, 'y': y, 'width': w, 'height': h, 'z': (len(self.visuals)+1)*10, 'tabOrder': len(self.visuals)},
               'visual': visual}
        if filters:
            obj['filterConfig'] = {'filters': filters}
        self.visuals.append(obj)
        return obj

    def text(self, text, x, y, w, h, size=11, ink=GRAY, bold=False):
        obj = self.visual('textbox', None, None, x, y, w, h)
        obj['visual']['visualContainerObjects'] = report_objects(background=False)
        obj['visual']['visualContainerObjects']['padding'] = props(top=0, bottom=0, left=0, right=0)
        obj['visual']['objects'] = {'general': [{'properties': {'paragraphs': [{'textRuns': [{'value': text,
            'textStyle': {'fontFamily': 'Segoe UI', 'fontSize': f'{size}pt', 'color': ink, 'fontWeight': 'bold' if bold else 'normal'}}]}]}}]}
        return obj

    def cards(self, names, y=224):
        width = (1376 - (len(names)-1)*16)/len(names)
        for n, name in enumerate(names):
            self.visual('cardVisual', None, {'Data': [measure(name)]}, 32+n*(width+16), y, width, 112,
                        {'value': [{'selector': {'id': 'default'}, 'properties': {'fontSize': literal(24), 'fontColor': color(NAVY), 'displayUnits': literal(1)}}],
                         'label': [{'selector': {'id': 'default'}, 'properties': {'fontSize': literal(10), 'fontColor': color(GRAY)}}],
                         'padding': [{'selector': {'id': 'default'}, 'properties': {'paddingUniform': literal(8)}}]})

    def slicer(self, table, column, title, x=32, width=300, selected=None):
        obj = self.visual('slicer', title, {'Values': [(table, column)]}, x, 130, width, 78,
                           {'data': props(mode='Dropdown'), 'selection': props(singleSelect=False),
                            'header': props(show=False), 'items': props(fontSize=11)})
        if selected is not None:
            obj['visual']['objects']['general'] = [{'properties': {'filter': in_filter(table, column, selected)['filter']}}]
        return obj

    def table(self, title, columns, x, y, w, h, sort=None, filters=None):
        return self.visual('tableEx', title, {'Values': columns}, x, y, w, h,
                           {'columnHeaders': props(fontSize=10, autoSizeColumnWidth=True, columnAdjustment='growToFit'),
                            'values': props(fontSize=10), 'grid': props(gridVertical=False, rowPadding=7),
                            'total': props(totals=True)}, sort=sort, filters=filters)

    def chart(self, kind, title, category, values, x, y, w, h, filters=None, sort=None):
        return self.visual(kind, title, {'Category': [category], 'Y': [measure(v) for v in values]}, x, y, w, h,
                           {'legend': props(show=len(values)>1), 'categoryAxis': props(fontSize=10, showAxisTitle=False),
                            'valueAxis': props(fontSize=10, showAxisTitle=False), 'labels': props(show=False),
                            'dataPoint': [{'properties': {'defaultColor': color(TEAL)}}]}, filters, sort)

    def save(self):
        if self.interactions:
            self.obj['visualInteractions'] = self.interactions
        write(self.directory / 'page.json', self.obj)
        for visual in self.visuals:
            write(self.directory / 'visuals' / visual['name'] / 'visual.json', visual)


def build_pages():
    pages = []
    p = Page(1, '经营规模与服务质量一起看。商品金额不含运费；交付率、延迟率和低评分率各用自己的分母。')
    month = p.slicer('Calendar','YearMonth','下单月份 · 清空即整个窗口')
    p.slicer('Customers','customer_state','客户所在州',364)
    p.cards(['商品成交额（BRL）','下单订单数','已交付订单数','交付率','商品客单价（BRL）','延迟率'])
    p.chart('lineChart','月度商品成交额 / BRL',('Calendar','YearMonth'),['商品成交额（BRL）'],32,354,896,280,sort=(('Calendar','YearMonth'),'Ascending'))
    p.visual('cardVisual','低评分占有效评分订单',{'Data':[measure('低评分率')]},948,354,460,130)
    p.table('分母透明，异常可追溯',[measure(v) for v in ['可判断延迟订单数','无法判断延迟订单数','有有效评分订单数','低评分订单数']],948,500,460,134)
    p.table('月度经营明细',[('Calendar','YearMonth')]+[measure(v) for v in ['下单订单数','已交付订单数','交付率','商品成交额（BRL）','商品客单价（BRL）','延迟率','低评分率']],32,652,1376,198,sort=(('Calendar','YearMonth'),'Ascending'))
    pages.append(p)

    p=Page(2,'把成交额变化拆成订单量与客单价两项。瀑布图限单个完整月，趋势图始终保留整个经营窗口。')
    slicer=p.slicer('Calendar','YearMonth','比较月份 · 默认 2017-11',selected='2017-11')
    p.cards(['上月商品成交额（BRL）','商品成交额（BRL）','商品成交额环比','订单量贡献（BRL）','客单价贡献（BRL）'])
    waterfall=p.chart('waterfallChart','上月 → 订单量 → 客单价 → 本月 / BRL',('成交额拆解步骤','步骤'),['瀑布图金额（BRL）'],32,354,710,330,sort=(('成交额拆解步骤','步骤'),'Ascending'))
    trend=p.chart('lineChart','完整窗口月度趋势 / BRL',('Calendar','YearMonth'),['商品成交额（BRL）'],762,354,646,330,sort=(('Calendar','YearMonth'),'Ascending'))
    p.interactions.append({'source':slicer['name'],'target':trend['name'],'type':'NoFilter'})
    p.table('拆解对照',[('Calendar','YearMonth')]+[measure(v) for v in ['有商品明细的已交付订单数','商品客单价（BRL）','商品成交额变动（BRL）','订单量贡献（BRL）','客单价贡献（BRL）']],32,702,1376,148)
    pages.append(p)

    p=Page(3,'商品明细归入一个品类，客户州归入一笔订单。按品类去重的订单数不能跨品类相加。')
    p.slicer('Calendar','YearMonth','下单月份 · 选 2017-11 看增量')
    cat_slicer=p.slicer('ProductCategories','category_label','商品品类',364,400)
    p.cards(['商品成交额（BRL）','已交付运费（BRL）','运费占商品金额比','有商品明细的已交付订单数'])
    cat=p.chart('clusteredBarChart','品类商品金额 / BRL',('ProductCategories','category_label'),['商品成交额（BRL）'],32,354,656,248,sort=(measure('商品成交额（BRL）'),'Descending'))
    states=p.chart('clusteredBarChart','客户州商品金额 / BRL',('Customers','customer_state'),['商品成交额（BRL）'],708,354,700,248,sort=(measure('商品成交额（BRL）'),'Descending'))
    cat_table=p.table('品类结构与增量',[('ProductCategories','category_label')]+[measure(v) for v in ['商品成交额（BRL）','品类成交额占比','有商品明细的已交付订单数','分组成交额月变动（BRL）']],32,620,656,230,sort=(measure('商品成交额（BRL）'),'Descending'))
    state_table=p.table('客户州结构与运费负担',[('Customers','customer_state')]+[measure(v) for v in ['已交付订单数','商品成交额（BRL）','客户州成交额占比','商品客单价（BRL）','运费占商品金额比','分组成交额月变动（BRL）']],708,620,700,230,sort=(measure('商品成交额（BRL）'),'Descending'))
    for source in [cat,cat_table,cat_slicer]:
        for target in [states,state_table]:
            p.interactions.append({'source':source['name'],'target':target['name'],'type':'NoFilter'})
    pages.append(p)

    p=Page(4,'延迟按实际与预计送达自然日比较；阶段耗时按经过秒数换算天。每个阶段独立判断时长资格。')
    p.slicer('Calendar','YearMonth','下单月份')
    p.slicer('Customers','customer_state','客户所在州',364)
    p.cards(['已交付订单数','可判断延迟订单数','延迟订单数','延迟率','无法判断延迟订单数'])
    bands=in_filter('orders','delay_band_order',[1,2,3,4,5])
    p.chart('clusteredColumnChart','延迟程度与订单量',('orders','delay_band'),['可判断延迟订单数'],32,354,686,250,filters=[bands],sort=(('orders','delay_band'),'Ascending'))
    p.table('全流程有效样本与长尾',[measure(v) for v in ['审批有效订单数','审批 P50（天）','审批 P90（天）','交承运商有效订单数','交承运商 P50（天）','交承运商 P90（天）','运输有效订单数','运输 P50（天）','运输 P90（天）']],738,354,670,250)
    p.table('同州比较各阶段时长',[('Customers','customer_state')]+[measure(v) for v in ['可判断延迟订单数','延迟率','审批 P90（天）','交承运商 P90（天）','运输 P90（天）','运输有效订单数']],32,622,1376,228)
    pages.append(p)

    p=Page(5,'每单采用唯一最新有效评分，1–2 星为低评分。差异描述统计关联；州、月份和品类可能共同影响结果。')
    p.slicer('Calendar','YearMonth','下单月份')
    p.slicer('Customers','customer_state','客户所在州',364)
    p.cards(['有有效评分订单数','低评分订单数','低评分率','延迟组低评分率','按时或提前组低评分率'])
    score=p.chart('clusteredColumnChart','最新评分结构 / 有效订单数',('orders','latest_review_score'),['有有效评分订单数'],32,354,510,250,filters=[in_filter('orders','latest_review_score',[1,2,3,4,5])],sort=(('orders','latest_review_score'),'Ascending'))
    band=p.table('分档低评分与 Wilson 95% 区间',[('orders','delay_band')]+[measure(v) for v in ['可判断延迟订单数','有有效评分订单数','延迟样本评价覆盖率','低评分率','低评 Wilson 下限','低评 Wilson 上限']],562,354,846,250,filters=[in_filter('orders','delay_band_order',[1,2,3,4,5])],sort=(('orders','delay_band'),'Ascending'))
    state=p.table('州内比较与样本规模',[('Customers','customer_state')]+[measure(v) for v in ['有有效评分订单数','延迟组低评分率','按时或提前组低评分率','延迟与按时低评差（百分点）']],32,622,1376,228)
    for target in [band,state]:
        p.interactions.append({'source':score['name'],'target':target['name'],'type':'NoFilter'})
    pages.append(p)

    p=Page(6,'单卖家已交付订单固定快照。两种有效样本均 ≥50，且两项比率均高于平台基线才入选；簇用于描述特征。',True)
    p.slicer('SellerSnapshot','cluster_label','固定聚类分组')
    p.slicer('SellerSnapshot','seller_state','卖家所在州',364)
    p.cards(['参与聚类卖家数','建议核查卖家数','单卖家延迟基线','单卖家低评基线'])
    qualified=in_filter('SellerSnapshot','cluster_label',['簇 0','簇 1','簇 2'])
    p.visual('scatterChart','PCA 二维投影 / 累计解释方差 85.21%',{'X':[measure('PCA 横坐标')],'Y':[measure('PCA 纵坐标')],'Category':[('SellerSnapshot','seller_id')],'Series':[('SellerSnapshot','cluster_label')],'Tooltips':[measure(v) for v in ['卖家单卖家订单数','卖家延迟率','卖家低评分率']]},32,354,656,265,filters=[qualified])
    p.table('簇画像与规则入选',[('SellerSnapshot','cluster_label')]+[measure(v) for v in ['参与聚类卖家数','建议核查卖家数','卖家单卖家订单数','卖家延迟率','卖家低评分率']],708,354,700,265,filters=[qualified])
    p.table('优先核查名单 · 按低评分涉及订单数排序',[('SellerSnapshot','seller_id'),('SellerSnapshot','seller_state'),('SellerSnapshot','cluster_label')]+[measure(v) for v in ['卖家单卖家订单数','卖家有效延迟订单数','卖家有评分订单数','卖家低评分订单数','卖家延迟订单数','卖家延迟率','卖家低评分率']],32,637,1376,213,filters=[in_filter('SellerSnapshot','rule_candidate',True)],sort=(measure('卖家低评分订单数'),'Descending'))
    pages.append(p)

    p=Page(7,'RFM 固定基准日 2018-09-01。先分单次与重复购买，再在组内计算 M 的 P75；当前筛选只改变展示人群。',True)
    p.slicer('CustomerRFM','frequency_group','购买频次组')
    p.slicer('CustomerRFM','recency_group','最近购买分组',364)
    p.cards(['RFM 客户数','RFM 已交付订单数','RFM 商品成交额（BRL）','RFM 客户人均商品金额（BRL）'])
    p.chart('clusteredColumnChart','单次与复购客户规模',('CustomerRFM','frequency_group'),['RFM 客户数'],32,354,510,250)
    p.visual('pivotTable','客户分群 × 金额档',{'Rows':[('CustomerRFM','frequency_group'),('CustomerRFM','recency_group')],'Columns':[('CustomerRFM','monetary_group')],'Values':[measure('RFM 客户数'),measure('RFM 商品成交额（BRL）')]},562,354,846,250,{'rowHeaders':props(fontSize=11),'columnHeaders':props(fontSize=10),'subTotals':props(rowSubtotals=False,columnSubtotals=False)})
    p.table('分群、贡献与组内门槛',[('CustomerRFM','frequency_group'),('CustomerRFM','recency_group'),('CustomerRFM','monetary_group')]+[measure(v) for v in ['RFM 客户数','RFM 已交付订单数','RFM 商品成交额（BRL）','RFM 组内 P75（BRL）']],32,622,1376,228)
    pages.append(p)

    p=Page(8,'下单月的后续购买订单，与首购月客户的固定窗口复购分开计算。未成熟窗口留空，成熟窗口中 0 人复购显示 0%。',True)
    p.slicer('MonthlyPurchase','purchase_month','左侧 · 下单月份')
    p.slicer('CustomerCohort','first_purchase_month','右侧 · 首购月份',364)
    p.slicer('CustomerCohort','followup_days','右侧 · 随访天数',696,260)
    p.cards(['后续购买订单占比','首购客户数','随访完整客户数','待成熟客户数','完整窗口复购率'])
    p.chart('columnChart','月度首次与后续购买订单',('MonthlyPurchase','purchase_month'),['窗口内首次购买订单数','窗口内后续购买订单数'],32,354,656,280,sort=(('MonthlyPurchase','purchase_month'),'Ascending'))
    p.visual('pivotTable','固定 30 / 60 / 90 天完整窗口复购率',{'Rows':[('CustomerCohort','first_purchase_month')],'Columns':[('CustomerCohort','followup_days')],'Values':[measure('完整窗口复购率')]},708,354,700,496,{'rowHeaders':props(fontSize=11),'columnHeaders':props(fontSize=11),'subTotals':props(rowSubtotals=False,columnSubtotals=False)},sort=(('CustomerCohort','first_purchase_month'),'Ascending'))
    p.table('观察资格与复购人数',[('CustomerCohort','first_purchase_month'),('CustomerCohort','followup_days')]+[measure(v) for v in ['首购客户数','随访完整客户数','待成熟客户数','窗口内复购客户数']],32,652,656,198)
    pages.append(p)
    for page in pages:
        page.save()
    return pages


def build_report(pages):
    write(OUT / 'Olist.pbip', {'$schema': SCHEMA + 'pbip/pbipProperties/1.0.0/schema.json', 'version':'1.0',
                              'artifacts':[{'report':{'path':'Olist.Report'}}], 'settings':{'enableAutoRecovery':True}})
    write(REPORT / 'definition.pbir', {'$schema':SCHEMA+'item/report/definitionProperties/2.0.0/schema.json','version':'4.0','datasetReference':{'byPath':{'path':'../Olist.SemanticModel'}}})
    write(REPORT / 'definition/version.json', {'$schema': SCHEMA+'item/report/definition/versionMetadata/1.0.0/schema.json','version':'2.0.0'})
    write(REPORT / 'definition/pages/pages.json', {'$schema':SCHEMA+'item/report/definition/pagesMetadata/1.0.0/schema.json','pageOrder':[p.name for p in pages],'activePageName':pages[0].name})
    theme = {'name':'Olist Operations', 'dataColors':[TEAL,CORAL,'#597CB2','#D8A647','#6A967C','#A5779E'],
             'background':'#FFFFFF','foreground':NAVY,'tableAccent':TEAL,
             'textClasses':{'title':{'fontFace':'Segoe UI','fontSize':13,'color':NAVY},
                            'label':{'fontFace':'Segoe UI','fontSize':10,'color':GRAY},
                            'callout':{'fontFace':'Segoe UI','fontSize':25,'color':NAVY}},
             'visualStyles':{'*':{'*':{'title':[{'fontSize':12,'fontColor':NAVY}],
                                        'background':[{'color':{'solid':{'color':'#FFFFFF'}}}],
                                        'legend':[{'fontSize':10}]}},
                             'cardVisual':{'*':{'value':[{'displayUnits':1,'fontSize':24}],'label':[{'fontSize':10}]}},
                             'waterfallChart':{'*':{'sentimentColors':[{'increaseFill':{'solid':{'color':TEAL}},'decreaseFill':{'solid':{'color':CORAL}},'totalFill':{'solid':{'color':NAVY}}}]}}}}
    write(REPORT/'StaticResources/RegisteredResources/OlistTheme.json', theme)
    write(REPORT/'definition/report.json', {'$schema':SCHEMA+'item/report/definition/report/3.0.0/schema.json',
        'themeCollection':{'baseTheme':{'name':'CY23SU04','reportVersionAtImport':{'visual':'1.8.0','page':'2.0.0','report':'3.0.0'},'type':'SharedResources'},
                           'customTheme':{'name':'OlistTheme','reportVersionAtImport':{'visual':'1.8.0','page':'2.0.0','report':'3.0.0'},'type':'RegisteredResources'}},
        'resourcePackages':[{'name':'RegisteredResources','type':'RegisteredResources','items':[{'name':'OlistTheme','path':'OlistTheme.json','type':'CustomTheme'}]}],
        'filterConfig':{'filters':[in_filter('Calendar','经营窗口',True)]},
        'settings':{'useStylableVisualContainerHeader':True,'exportDataMode':'AllowSummarized','defaultFilterActionIsDataFilter':True}})


def main():
    tables=prepare_data()
    prepare_measures()
    build_model(tables)
    pages=build_pages()
    build_report(pages)
    print(json.dumps({'project':str(OUT/'Olist.pbip'),'pages':len(pages),'visuals':sum(len(p.visuals) for p in pages),
                      'tables':len(tables),'measures':len(MEASURES),'rows':{k:len(v) for k,v in tables.items()}},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
