"""Create a GitHub-ready full snapshot without environments, secrets or caches."""
import ast
import hashlib
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT.parent / 'releases' / '2026-11-19'
SKIP_DIRS = {'.venv', '__pycache__', '.ipynb_checkpoints', '.git', '.pbi', 'node_modules'}
FOLDERS = {'src', 'sql', 'tests', 'config', 'docs', 'notebooks', 'reports', 'data', 'powerbi', 'tools', '.github'}
ROOT_FILES = {'LICENSE', 'DATA_LICENSE.md', '.gitignore', 'requirements.txt', 'requirements-dev.txt',
              'requirements-parquet.txt', 'requirements-mysql.txt', 'requirements-notebooks.txt'}


def selected(path):
    rel = path.relative_to(ROOT)
    if any(part in SKIP_DIRS for part in rel.parts):
        return False
    if rel.as_posix().startswith(('powerbi/_tools/deps/', 'powerbi/_tools/reference/')):
        return False
    if path.name in {'desktop_check.ps1', 'GITHUB_README.md'}:
        return False
    if path.suffix in {'.pyc', '.pyo', '.log', '.tmp'} or path.name.startswith('.env'):
        return False
    return rel.parts[0] in FOLDERS or (len(rel.parts)==1 and path.name in ROOT_FILES)


def main():
    DEST.mkdir(parents=True,exist_ok=True)
    label = 'olist-operations-analytics-github'
    stage = DEST / label
    if stage.exists():
        stage = DEST / (label + '-' + datetime.now().strftime('%H%M%S'))
    stage.mkdir()
    count = 0
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file() or not selected(path):
            continue
        if path.stat().st_size >= 100*1024*1024:
            raise ValueError('GitHub regular file limit exceeded: '+str(path))
        dest = stage / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,dest)
        count+=1

    template = ROOT/'docs/GITHUB_README.md'
    readme = (template if template.is_file() else ROOT/'README.md').read_text(encoding='utf-8')
    readme = readme.replace('\npython .\\src\\', '\n.\\.venv\\Scripts\\python.exe .\\src\\')
    readme = readme.replace('\npython .\\powerbi\\', '\n.\\.venv\\Scripts\\python.exe .\\powerbi\\')
    (stage/'README.md').write_text(readme,encoding='utf-8')
    (stage/'docs/历史学习入口.md').write_text(
        (ROOT/'README.md').read_text(encoding='utf-8').replace('](docs/','](').replace('](reports/','](../reports/'),
        encoding='utf-8')
    (stage/'.gitignore').write_text('''# Environments, machine settings and generated validation caches
.venv/
venv/
__pycache__/
*.py[cod]
.ipynb_checkpoints/
.env
.env.*
!.env.example
*.log
*.tmp
.DS_Store
Thumbs.db
.vscode/
.idea/
archive/
data/raw/
powerbi/_tools/deps/
powerbi/_tools/reference/
powerbi/**/.pbi/
*.pbix
*.zip
releases/
# The full handoff deliberately contains processed snapshots and their license.
# Exclude data/processed/ and powerbi/Olist/data/ here if storing data in Releases.
''',encoding='utf-8')
    (stage/'.gitattributes').write_text('''# Preserve snapshot hashes across Windows and Unix checkouts.
* -text
*.png binary
*.jpg binary
*.parquet binary
''',encoding='utf-8')

    # A Power Query parameter is absolute at runtime. Make its initial value point
    # at this copy; set_data_path.py rebinds it on the recipient's machine.
    model_path=stage/'powerbi/Olist/Olist.SemanticModel/model.bim'
    model=json.loads(model_path.read_text(encoding='utf-8'))
    parameter=next(p for p in model['model']['expressions'] if p['name']=='DataRoot')
    parameter['expression']='"'+str(stage/'powerbi/Olist/data')+'" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'
    model_path.write_text(json.dumps(model,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    # Remove original machine paths from run metadata while preserving values,
    # source hashes and the configuration manifest bytes used by the loader.
    def clean(value):
        if isinstance(value,dict): return {k:clean(v) for k,v in value.items()}
        if isinstance(value,list): return [clean(v) for v in value]
        if isinstance(value,str):
            value=value.replace(str(ROOT),'${PROJECT_ROOT}').replace(str(ROOT.parent/'archive'),'${RAW_DATA_DIR}')
        return value
    for path in (stage/'reports').rglob('*.json'):
        value=json.loads(path.read_text(encoding='utf-8-sig'))
        path.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')

    for file in stage.rglob('*.py'):
        ast.parse(file.read_text(encoding='utf-8-sig'),filename=str(file))
    for file in stage.rglob('*.ipynb'):
        value=json.loads(file.read_text(encoding='utf-8-sig'))
        assert value['nbformat']==4 and isinstance(value['cells'],list),file
    for link in re.findall(r'\]\(([^)]+)\)',readme):
        if not re.match('https?://',link):
            assert (stage/link.split('#')[0]).exists(),link
    # No real credentials or private keys, with common placeholder examples allowed.
    credential_pattern=re.compile(r'(?:ghp_[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----)')
    for file in stage.rglob('*'):
        if file.is_file() and file.suffix in {'.py','.ps1','.sql','.json','.ipynb','.txt','.md','.yml','.yaml'}:
            assert not credential_pattern.search(file.read_text(encoding='utf-8-sig')),file

    validation={
        'packaged_on':'2026-11-19', 'included_source_files':count,
        'python_unit_tests':'27 passed before packaging',
        'analysis_export':'22 CSV tables, numeric controls passed',
        'powerbi':'PBIP static schema/binding checks passed; Desktop rendering not certified',
        'source_csv_included':False,'processed_results_included':True,
        'excludes':['virtual environment','dependency/schema caches','machine environment files','temporary GUI helpers'],
        'license':'MIT for original code; CC BY-NC-SA 4.0 for Olist data and derived outputs'}
    (stage/'PACKAGE_INFO.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    files=sorted(p for p in stage.rglob('*') if p.is_file())
    hashes=[hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(stage).as_posix() for p in files]
    (stage/'MANIFEST.sha256').write_text('\n'.join(hashes)+'\n',encoding='utf-8')
    archive=stage.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as zipped:
        for path in sorted(stage.rglob('*')):
            if path.is_file(): zipped.write(path,arcname=stage.name+'/'+path.relative_to(stage).as_posix())
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        for row in hashes:
            expected,relative=row.split('  ',1)
            assert hashlib.sha256(zipped.read(stage.name+'/'+relative)).hexdigest()==expected
    checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(checksum+'  '+archive.name+'\n',encoding='utf-8')
    print(json.dumps({'zip':str(archive),'readme':str(stage/'README.md'),'files':len(files)+1,
                      'zip_mib':round(archive.stat().st_size/1024/1024,2),'sha256':checksum},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
