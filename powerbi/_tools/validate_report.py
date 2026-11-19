"""Offline Microsoft schema validation plus model/visual binding and data controls."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'deps'))
import jsonschema
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / 'powerbi/Olist'
CACHE = Path(__file__).parent / 'reference'
schemas = {}
for file in CACHE.rglob('*.json'):
    if '-tree' in file.name:
        continue
    value = json.loads(file.read_text(encoding='utf-8'))
    schemas['https://developer.microsoft.com/json-schemas/' + file.relative_to(CACHE).as_posix()] = value
    if '$id' in value:
        schemas[value['$id']] = value

errors = []
checked = 0
for file in PROJECT.rglob('*'):
    if file.suffix not in ('.json', '.pbip', '.pbir', '.pbism'):
        continue
    obj = json.loads(file.read_text(encoding='utf-8'))
    if '$schema' not in obj:
        continue
    schema = schemas[obj['$schema']]
    resolver = jsonschema.RefResolver.from_schema(schema, store=schemas)
    for error in jsonschema.Draft7Validator(schema, resolver=resolver).iter_errors(obj):
        errors.append((str(file.relative_to(PROJECT)), '/'.join(map(str,error.path)), error.message[:500]))
    checked += 1

model = json.loads((PROJECT / 'Olist.SemanticModel/model.bim').read_text(encoding='utf-8'))['model']
tables = {t['name']: {c['name'] for c in t['columns']} for t in model['tables']}
measures = {m['name']: m for t in model['tables'] for m in t.get('measures', [])}
frames = {name: pd.read_parquet(PROJECT / 'data' / (name + '.parquet')) for name in tables}

def check_bindings(obj):
    if isinstance(obj, dict):
        for kind in ('Column','Measure'):
            if kind in obj:
                value=obj[kind]
                table=value.get('Expression',{}).get('SourceRef',{}).get('Entity')
                if table:
                    if kind=='Column':
                        assert value['Property'] in tables[table], (table, value)
                    else:
                        assert value['Property'] in measures, value
        for value in obj.values(): check_bindings(value)
    elif isinstance(obj,list):
        for value in obj: check_bindings(value)

visuals=list(PROJECT.glob('Olist.Report/definition/pages/*/visuals/*/visual.json'))
for file in visuals:
    check_bindings(json.loads(file.read_text(encoding='utf-8')))
for measure in measures.values():
    expr=measure['expression']
    pattern=r"(?:'([^']+)'|(\w+))\[([^\]]+)\]"
    for quoted,plain,col in re.findall(pattern,expr):
        table=quoted or plain
        assert col in tables[table], (measure['name'],table,col)
    unqualified=re.sub(pattern,'',expr)
    for name in re.findall(r'\[([^\]]+)\]',unqualified):
        assert name in measures, (measure['name'],name)
for rel in model['relationships']:
    child=frames[rel['fromTable']][rel['fromColumn']]
    parent=frames[rel['toTable']][rel['toColumn']]
    assert parent.notna().all() and parent.is_unique, rel
    assert child.isin(parent).all(), rel
orders, items=frames['orders'], frames['order_items']
window=orders.order_purchase_timestamp.between('2017-01-01','2018-09-01',inclusive='left')
delivered=orders[window & orders.order_status.eq('delivered')]
sale=items[items.order_id.isin(delivered.order_id)]
assert len(orders)==99441 and len(items)==112650
assert int(window.sum())==99092 and len(delivered)==96211
assert sale.price_cents.sum()==1318102713 and sale.freight_cents.sum()==219209288
assert delivered.delay_band_order.notna().sum()==96203
assert delivered.delay_band_order.ge(2).sum()==6531
assert frames['SellerSnapshot'].rule_candidate.sum()==102
assert frames['SellerSnapshot'].pc1.count()==408
assert frames['CustomerRFM'].customer_count.sum()==93104
assert frames['CustomerRFM'].delivered_orders.sum()==96211
assert len(list(PROJECT.glob('Olist.Report/definition/pages/*/page.json')))==8
result={'schema_documents_checked':checked,'schema_errors':errors,'pages':8,'visuals':len(visuals),'measures':len(measures),
        'data_controls':'passed','report_bindings':'passed','engine_validation':'Power BI Desktop still required'}
(PROJECT / 'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
sys.exit(bool(errors))
