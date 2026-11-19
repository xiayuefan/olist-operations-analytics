"""Rebind the bundled PBIP data parameter after downloading or moving the folder.

Run from the repository root: python powerbi/set_data_path.py
Close this project's Power BI Desktop window before changing the on-disk model.
"""
import json
from pathlib import Path


def main():
    project = Path(__file__).resolve().parent / 'Olist'
    path = project / 'Olist.SemanticModel/model.bim'
    model = json.loads(path.read_text(encoding='utf-8'))
    parameter = next(item for item in model['model']['expressions'] if item['name'] == 'DataRoot')
    folder = project / 'data'
    if not folder.is_dir() or not (folder / 'orders.parquet').is_file():
        raise FileNotFoundError('Bundled Power BI data not found: ' + str(folder))
    parameter['expression'] = '"' + str(folder).replace('"', '""') + '" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'
    path.write_text(json.dumps(model, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Updated DataRoot:', folder)
    print('Open:', project / 'Olist.pbip')


if __name__ == '__main__':
    main()
