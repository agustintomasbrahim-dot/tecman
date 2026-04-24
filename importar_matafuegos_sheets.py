import json
import re
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '/Users/agustin/.openclaw/workspace/google_calendar')
from gauth import sheets  # type: ignore

SPREADSHEET_ID = '1Rbryp2kVMMm2V8HAPJ9D-8De0t6rYArT5H5EHqh0rUg'
BASE = Path(__file__).parent
DATA_FILE = BASE / 'data' / 'matafuegos.json'
STATE_FILE = BASE / 'data' / 'matafuegos_import_state.json'
BATCH_SIZE = 5


def parse_date(value: str) -> str:
    value = (value or '').strip()
    if not value:
        return ''
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d/%m/%y'):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return value


def normalize_title(title: str):
    m = re.match(r'^(\d+)\s*-\s*(.+)$', title.strip())
    if m:
        return m.group(1).zfill(3), f'Sucursal {m.group(1).zfill(3)}', m.group(2).strip()
    m = re.match(r'^(\d+)-(.+)$', title.strip())
    if m:
        return m.group(1).zfill(3), f'Sucursal {m.group(1).zfill(3)}', m.group(2).strip()
    return '', title.strip(), title.strip()


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text())
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def main():
    svc = sheets()
    meta = svc.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    titles = [sh['properties']['title'] for sh in meta['sheets']]

    state = load_json(STATE_FILE, {'offset': 0, 'updated_at': None})
    start = state.get('offset', 0)
    end = min(start + BATCH_SIZE, len(titles))
    chunk = titles[start:end]
    if not chunk:
        print('DONE')
        state['offset'] = 0
        state['updated_at'] = datetime.utcnow().isoformat()
        save_json(STATE_FILE, state)
        return

    ranges = [f"'{t}'!A4:E53" for t in chunk]
    resp = svc.spreadsheets().values().batchGet(spreadsheetId=SPREADSHEET_ID, ranges=ranges).execute()
    data = load_json(DATA_FILE, {'matafuegos': []})
    items = data.get('matafuegos', [])

    processed = []
    for vr in resp.get('valueRanges', []):
        rng = vr['range']
        title = rng.split("'!")[0].strip("'") if "'!" in rng else rng.split('!')[0]
        suc_num, sucursal, suc_nombre = normalize_title(title)
        # drop previous imported rows from same source sheet so reruns stay idempotent
        items = [m for m in items if m.get('origen') != 'google_sheet_matafuegos' or m.get('sheet_title') != title]
        vals = vr.get('values', [])
        count = 0
        for row in vals:
            nro = row[0].strip() if len(row) > 0 else ''
            tipo = row[1].strip() if len(row) > 1 else ''
            capacidad = row[2].strip() if len(row) > 2 else ''
            fecha_carga = parse_date(row[3]) if len(row) > 3 else ''
            fecha_vto = parse_date(row[4]) if len(row) > 4 else ''
            if not any([tipo, capacidad, fecha_carga, fecha_vto]):
                continue
            items.append({
                'id': uuid.uuid4().hex[:12],
                'sucursal': sucursal,
                'sucursal_num': suc_num,
                'local_nombre': suc_nombre,
                'ubicacion': '',
                'tipo': tipo or 'Sin tipo',
                'cantidad': 1,
                'capacidad': capacidad,
                'fecha_carga': fecha_carga,
                'fecha_vencimiento': fecha_vto,
                'estado_manual': '',
                'origen': 'google_sheet_matafuegos',
                'sheet_title': title,
                'nro_extintor': nro,
                'importado_at': datetime.utcnow().isoformat(),
            })
            count += 1
        processed.append((title, count))

    data['matafuegos'] = items
    save_json(DATA_FILE, data)
    state['offset'] = end
    state['updated_at'] = datetime.utcnow().isoformat()
    save_json(STATE_FILE, state)

    for title, count in processed:
        print(f'{title}: {count}')
    print(f'NEXT_OFFSET={end}')


if __name__ == '__main__':
    main()
