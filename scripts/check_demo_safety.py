"""Fail closed if a purported public demo includes original CSV IDs or private files."""
from pathlib import Path
import csv
import sys


def check(root):
    root = Path(root)
    prohibited = [root/'part1',root/'instance',root/'.env',root/'.streamlit'/'secrets.toml',
                  root/'data'/'orders.csv',root/'data'/'support_tickets.csv']
    if any(x.exists() for x in prohibited):
        raise ValueError('Demo contains a private/restricted directory or file.')
    for filename, idfield, prefix in [('orders_clean.csv','order_id','ORD-81'),
                                       ('support_tickets_clean.csv','ticket_id','TKT-91')]:
        path = root/'data'/filename
        if not path.exists():
            raise ValueError(f'Missing synthetic dataset: {path}')
        with path.open(newline='',encoding='utf-8') as handle:
            data=list(csv.DictReader(handle))
        if not 10 <= len(data) <= 100:
            raise ValueError(f'Unexpected number of synthetic rows in {filename}.')
        if any(not item[idfield].startswith(prefix) or not item['customer_id'].startswith('CUST-DEMO-')
               for item in data):
            raise ValueError('Dataset contains non-synthetic-looking identifiers.')
        if 'customer_message' in data[0] and any('Synthetic demonstration' not in r['customer_message'] for r in data):
            raise ValueError('Non-synthetic customer message found in demo data.')
    if not (root/'DEMO_DATA_ONLY.md').exists():
        raise ValueError('Demo lacks synthetic-data notice.')
    return True


if __name__ == '__main__':
    dest = sys.argv[1] if len(sys.argv) > 1 else '.'
    check(dest)
    print('Public demo safety checks passed.')
