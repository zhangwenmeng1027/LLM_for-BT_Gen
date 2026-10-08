# -*- coding: utf-8 -*-
"""Run BehaVerify LTL verification for every benchmark tree; collect results."""
import os
import re
import json
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TREES = os.path.join(HERE, 'trees')
OUT = os.path.join(HERE, '_verify_out')
PY = sys.executable
NUXMV = r'D:\tools_nusmv\NuSMV-2.7.1-win64\NuSMV-2.7.1-win64\bin\NuSMV.exe'

SPEC_RE = re.compile(r'-- specification\s+(.+?)\s+is\s+(true|false)', re.IGNORECASE)


def main():
    os.makedirs(OUT, exist_ok=True)
    results = {}
    for fn in sorted(os.listdir(TREES)):
        if not fn.endswith('.tree'):
            continue
        name = fn[:-5]
        task_out = os.path.join(OUT, name)
        os.makedirs(task_out, exist_ok=True)
        cmd = [PY, '-m', 'behaverify', 'nuxmv', os.path.join(TREES, fn), task_out,
               '--generate', '--do_not_trim', '--ltl', '--nuxmv_path', NUXMV, '--overwrite']
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                               cwd=HERE, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = -1
        outfile = os.path.join(task_out, 'nuxmv', name + '_output.txt')
        specs = []
        if os.path.exists(outfile):
            with open(outfile, encoding='utf-8', errors='replace') as f:
                content = f.read()
            for m in SPEC_RE.finditer(content):
                specs.append({'spec': m.group(1).strip(), 'result': m.group(2).lower()})
        results[name] = {'rc': rc, 'n_specs': len(specs), 'specs': specs,
                         'n_true': sum(1 for s in specs if s['result'] == 'true'),
                         'n_false': sum(1 for s in specs if s['result'] == 'false')}
        flag = 'OK ' if rc == 0 and results[name]['n_false'] == 0 else ' !!'
        print('{} {:28s} rc={} specs={} true={} false={}'.format(
            flag, name, rc, results[name]['n_specs'],
            results[name]['n_true'], results[name]['n_false']), flush=True)
    with open(os.path.join(HERE, '_verify_results.json'), 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    tot_t = sum(r['n_true'] for r in results.values())
    tot_f = sum(r['n_false'] for r in results.values())
    print('TOTAL: tasks={} true={} false={}'.format(len(results), tot_t, tot_f))


if __name__ == '__main__':
    main()
