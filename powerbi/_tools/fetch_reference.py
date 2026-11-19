"""Cache Microsoft's public format specifications for offline validation."""
import json
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urljoin, urldefrag

ROOT = Path(__file__).resolve().parent / 'reference'
ROOT.mkdir(parents=True, exist_ok=True)

def fetch(url):
    return urlopen(Request(url, headers={'User-Agent': 'Olist-PowerBI-format-validation'}), timeout=45).read()

for repo in ('microsoft/Analysis-Services', 'microsoft/skills-for-fabric'):
    tree = json.loads(fetch('https://api.github.com/repos/' + repo + '/git/trees/master?recursive=1').decode()) if repo.endswith('Analysis-Services') else json.loads(fetch('https://api.github.com/repos/' + repo + '/git/trees/main?recursive=1').decode())
    (ROOT / (repo.split('/')[-1] + '-tree.json')).write_text(json.dumps(tree), encoding='utf-8')
    paths = [p['path'] for p in tree.get('tree', []) if p['path'].endswith(('.pbip', '/visual.json', '/model.bim', '/model.tmdl'))]
    print(repo, len(tree.get('tree', [])), '\n'.join(paths[:12]))

base = 'https://developer.microsoft.com/json-schemas/fabric/'
pending = [base + p for p in [
    'pbip/pbipProperties/1.0.0/schema.json', 'item/report/definitionProperties/2.0.0/schema.json',
    'item/semanticModel/definitionProperties/1.0.0/schema.json',
    'item/report/definition/report/3.0.0/schema.json', 'item/report/definition/page/2.0.0/schema.json',
    'item/report/definition/pagesMetadata/1.0.0/schema.json', 'item/report/definition/versionMetadata/1.0.0/schema.json',
    'item/report/definition/visualContainer/2.3.0/schema.json',
]]
seen = set()
while pending:
    url = pending.pop()
    if url in seen:
        continue
    seen.add(url)
    data = fetch(url)
    relative = url.split('/json-schemas/')[1]
    dest = ROOT / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    schema = json.loads(data)
    def refs(obj):
        if isinstance(obj, dict):
            for k, value in obj.items():
                if k == '$ref' and not value.startswith('#'):
                    pending.append(urldefrag(urljoin(url, value))[0])
                else:
                    refs(value)
        elif isinstance(obj, list):
            for value in obj:
                refs(value)
    refs(schema)
print('Cached schemas:', len(seen))
for name in ('powerbi-report-author-cli.md', 'powerbi-desktop.md', 'model-binding.md', 'card.md', 'slicers.md', 'table.md', 'cartesian.md', 'preview.md'):
    url = 'https://raw.githubusercontent.com/microsoft/skills-for-fabric/main/skills/powerbi-report-cli/references/authoring/' + name
    (ROOT / name).write_bytes(fetch(url))
print('Reference examples cached')

# Python 3.8 compatible validation libraries, extracted locally without changing the project environment.
import io
import zipfile
deps = ROOT.parent / 'deps'
deps.mkdir(exist_ok=True)
for package, version in [('jsonschema', '4.17.3'), ('attrs', '23.2.0'), ('pyrsistent', '0.19.3')]:
    metadata = json.loads(fetch(f'https://pypi.org/pypi/{package}/{version}/json'))
    candidates = [item for item in metadata['urls'] if item['filename'].endswith('.whl') and (
        'none-any' in item['filename'] or ('cp38' in item['filename'] and 'win_amd64' in item['filename']))]
    wheel = candidates[0]
    zipfile.ZipFile(io.BytesIO(fetch(wheel['url']))).extractall(deps)
print('Validation libraries ready')
