# -*- coding: utf-8 -*-
"""Create the BehaVerify benchmark xlsx, mirroring My_benchmark_ok.xlsx format.

Columns A-D mirror the original (Task / description / LTL / BT); the LTL column
holds the BehaVerify DSL specifications (one LTLSPEC per line) and the BT column
holds the BehaVerify tree notation.  Extra columns E-H record the generated
.tree file and the verification outcome (NuSMV results).
"""
import json
import os

import openpyxl
from openpyxl.styles import Font, Alignment

HERE = os.path.dirname(os.path.abspath(__file__))
NEW = os.path.join(HERE, '_benchmark_new.json')
VER = os.path.join(HERE, '_verify_results.json')
OUT = os.path.join(HERE, 'Behaverify_benchmark.xlsx')

HEADERS = ['Task', 'description', 'LTL', 'BT', 'tree_file',
           'n_specs', 'n_true', 'n_false', 'result']


def main():
    with open(NEW, encoding='utf-8') as f:
        rows = json.load(f)
    ver = {}
    if os.path.exists(VER):
        with open(VER, encoding='utf-8') as f:
            ver = json.load(f)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'benchmark'
    bold = Font(bold=True)
    for c, h in enumerate(HEADERS, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = bold
    for i, r in enumerate(rows, start=2):
        task = r['task']
        specs = r.get('specs') or []
        ltl_col = '\n'.join('LTLSPEC {' + s + '}' for s in specs)
        bt_col = r.get('bt_pretty', '')
        v = ver.get(task, {})
        n_specs, n_true, n_false = v.get('n_specs', 0), v.get('n_true', 0), v.get('n_false', 0)
        if not v:
            result = 'NOT RUN'
        elif v.get('rc', 1) != 0 and n_specs == 0:
            result = 'ERROR'
        elif n_false == 0 and n_true == n_specs and n_specs > 0:
            result = 'ALL TRUE'
        elif n_true == 0 and n_false > 0:
            result = 'ALL FALSE'
        else:
            result = 'MIXED ({} true / {} false)'.format(n_true, n_false)
        ws.cell(row=i, column=1, value=task)
        ws.cell(row=i, column=2, value=r['description'])
        ws.cell(row=i, column=3, value=ltl_col)
        ws.cell(row=i, column=4, value=bt_col)
        ws.cell(row=i, column=5, value=r.get('tree_file', ''))
        ws.cell(row=i, column=6, value=n_specs)
        ws.cell(row=i, column=7, value=n_true)
        ws.cell(row=i, column=8, value=n_false)
        ws.cell(row=i, column=9, value=result)
    widths = {1: 26, 2: 60, 3: 70, 4: 60, 5: 30, 6: 8, 7: 8, 8: 8, 9: 18}
    for c, w in widths.items():
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = w
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical='top')
    wb.save(OUT)
    print('saved', OUT, 'rows=', len(rows))


if __name__ == '__main__':
    main()
