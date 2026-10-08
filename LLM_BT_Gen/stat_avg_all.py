# -*- coding: utf-8 -*-
"""All-groups averaged statistics (mean ± std): every (model x baseline) found.

Scans <dir> for summary_<model>_<N>.json (full baseline) and
summary_<model>_<baseline>_<N>.json (noce / withbt), ANY model, ANY run index
-- nothing has to be declared.  The same LLM under the same baseline forms ONE
group; every metric is reported as MEAN ± STD over that group's run files
(sample std, n-1; 0.0 for a single run).

Per-run metrics (each summary file = one run over the whole benchmark):
    solved/run, solve %, calls/task* (FAILED tasks counted at the call cap =
    that run's max_rounds, or --max-retries), calls/solved, calls/run,
    tokens/task, tokens/run, cost/run $, cost/task $, time/solved s,
    time/task s, llm s/task, verify s/task.

Writes ALL results into ONE xlsx:
    <dir>/statistics_avg_all.xlsx
      sheet "summary"  one row per group, metrics as "mean ± std" strings
                       (paper-ready)
      sheet "mean"     same table, pure numeric means  -> pivot / plotting
      sheet "std"      same table, pure numeric stds
      sheet "per_run"  tidy long format: Model | Baseline | Run | metrics
                       (one row per run file, for box plots / error bars)

Run:
    python stat_avg_all.py                    # all groups, all run files
    python stat_avg_all.py --last 5           # per group only the newest 5 runs
    python stat_avg_all.py --model gpt-4o     # one model (all baselines)
    python stat_avg_all.py --baseline noce    # one baseline (all models)
    python stat_avg_all.py --max-retries 5    # override the failed-task cap
"""
import argparse
import json
import re
import statistics
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

HERE = Path(__file__).resolve().parent
FILENAME_RE = re.compile(r'summary_(.+)_(\d+)\.json$')
VARIANT_ORDER = {'full': 0, 'noce': 1, 'withbt': 2}

# (key, xlsx label, decimals)
METRICS = [('succ', 'solved/run', 1),
           ('rate', 'solve %', 1),
           ('calls_task', 'calls/task*', 2),
           ('calls_solved', 'calls/solved', 2),
           ('calls_tot', 'calls/run', 1),
           ('tokens_task', 'tokens/task', 1),
           ('tokens_run', 'tokens/run', 0),
           ('cost_run', 'cost/run ($)', 4),
           ('cost_task', 'cost/task ($)', 4),
           ('time_solved', 'time/solved (s)', 2),
           ('time_task', 'time/task (s)', 2),
           ('llm_task', 'llm s/task', 2),
           ('verify_task', 'verify s/task', 2)]

CONSOLE_KEYS = [('succ', 'solved/run', 1), ('rate', 'solve %', 1),
                ('calls_task', 'calls/task*', 2), ('calls_tot', 'calls/run', 1),
                ('tokens_task', 'tokens/task', 0), ('cost_run', 'cost/run($)', 4),
                ('time_task', 'time/task(s)', 2), ('llm_task', 'llm s/task', 2)]


def discover(d):
    """All (model, baseline, [(run_no, cap, task_records)]) groups in d."""
    found = {}
    for p in sorted(d.glob('summary*.json'),
                    key=lambda q: (FILENAME_RE.search(q.name).group(1),
                                   int(FILENAME_RE.search(q.name).group(2)))
                    if FILENAME_RE.search(q.name) else (q.name, 0)):
        try:
            with open(p, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print('skipping unreadable {}: {}'.format(p.name, e))
            continue
        m = FILENAME_RE.search(p.name)
        model = data.get('model') or (m.group(1) if m else p.stem)
        variant = data.get('baseline') or 'full'
        tasks = data.get('results') or []
        if not tasks:
            continue
        found.setdefault((model, variant), []).append(
            (int(m.group(2)) if m else 0, data.get('max_rounds') or 5, tasks))
    return [(model, variant, sorted(runs))
            for (model, variant), runs in
            sorted(found.items(), key=lambda kv: (kv[0][0],
                                                  VARIANT_ORDER.get(kv[0][1], 9)))]


def _avg(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else None


def run_metrics(tasks, cap):
    """Per-run metric dict from one summary file's task records."""
    n = len(tasks)
    solved = sum(1 for t in tasks if t.get('success'))
    calls, calls_ok = [], []
    for t in tasks:
        c = t.get('n_calls')
        if c is None:                                  # older files: rounds
            c = t.get('rounds') or 0
        if not t.get('success'):
            c = max(c, cap)                            # failed -> call cap
        calls.append(c)
        if t.get('success'):
            calls_ok.append(c)
    costs = [t.get('cost_usd') for t in tasks]
    cost_ok = None if any(c is None for c in costs) else sum(costs)
    return {'succ': solved,
            'rate': round(100.0 * solved / n, 1) if n else None,
            'calls_task': _avg(calls),
            'calls_solved': _avg(calls_ok),
            'calls_tot': sum(calls),
            'tokens_task': _avg([t.get('total_tokens') for t in tasks]),
            'tokens_run': sum(t.get('total_tokens') or 0 for t in tasks),
            'cost_run': cost_ok,
            'cost_task': (cost_ok / n if cost_ok is not None else None),
            'time_solved': _avg([t.get('time_s') for t in tasks if t.get('success')]),
            'time_task': _avg([t.get('time_s') for t in tasks]),
            'llm_task': _avg([t.get('llm_time_s') for t in tasks]),
            'verify_task': _avg([t.get('verify_time_s') for t in tasks])}


def _ms(vals, dec):
    """'mean ± std' string plus the raw mean/std (sample std, n-1)."""
    if not vals:
        return '-', None, None
    m = sum(vals) / len(vals)
    s = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return '{:.{d}f} ± {:.{d}f}'.format(m, s, d=dec), m, s


def main():
    ap = argparse.ArgumentParser(description='mean ± std statistics for every '
                                             '(model x baseline) group')
    ap.add_argument('--dir', default=str(HERE / 'results'),
                    help='results dir holding summary*.json')
    ap.add_argument('--last', type=int, default=None,
                    help='per group, use only the newest N run files '
                         '(e.g. --last 5 for the 5-repeat protocol)')
    ap.add_argument('--model', default=None, help='restrict to this model')
    ap.add_argument('--baseline', choices=['full', 'noce', 'withbt'], default=None,
                    help='restrict to this baseline')
    ap.add_argument('--max-retries', type=int, default=10,
                    help='fixed cap failed tasks are counted at in '
                         'calls/task* (default 10)')
    ap.add_argument('--out', default=None,
                    help='default <dir>/statistics_avg_all.xlsx')
    args = ap.parse_args()

    d = Path(args.dir)
    groups = discover(d)
    if args.model:
        groups = [g for g in groups if g[0] == args.model]
    if args.baseline:
        groups = [g for g in groups if g[1] == args.baseline]
    if args.last:
        groups = [(m, v, rs[-args.last:]) for m, v, rs in groups]
    if not groups:
        raise SystemExit('no matching summary*.json found in {}'.format(d))

    data = [(model, variant,
             [run_metrics(tasks, args.max_retries)
              for _no, cap, tasks in runs])
            for model, variant, runs in groups]

    # ------------------------------------------------------------------ xlsx
    wb = openpyxl.Workbook()

    def _fill(ws, title, mode):
        ws.title = title
        header = ['Model', 'Baseline', 'Runs'] + [l for _k, l, _d in METRICS]
        ws.append(header)
        for c in range(1, len(header) + 1):
            ws.cell(row=1, column=c).font = Font(bold=True)
        for model, variant, runs in data:
            cells = [model, variant, len(runs)]
            for key, _label, dec in METRICS:
                vals = [r[key] for r in runs if r.get(key) is not None]
                txt, m, s = _ms(vals, dec)
                cells.append(txt if mode == 'summary'
                             else (round(m, dec) if mode == 'mean' and m is not None
                                   else (round(s, dec) if mode == 'std' and s is not None
                                         else '-')))
            ws.append(cells)
        ws.column_dimensions['A'].width = 18
        ws.column_dimensions['B'].width = 10
        ws.column_dimensions['C'].width = 6
        for c in range(4, 4 + len(METRICS)):
            ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = 18
        ws.freeze_panes = 'D2'

    _fill(wb.active, 'summary', 'summary')
    _fill(wb.create_sheet('mean'), 'mean', 'mean')
    _fill(wb.create_sheet('std'), 'std', 'std')

    ws4 = wb.create_sheet('per_run')
    header4 = ['Model', 'Baseline', 'Run'] + [l for _k, l, _d in METRICS]
    ws4.append(header4)
    for c in range(1, len(header4) + 1):
        ws4.cell(row=1, column=c).font = Font(bold=True)
    for (model, variant, runs), (_m, _v, metrics) in zip(groups, data):
        for i, r in enumerate(metrics, 1):
            ws4.append([model, variant, i] +
                       [(round(r[k], dec) if r.get(k) is not None else '-')
                        for k, _l, dec in METRICS])
    for col, w in (('A', 18), ('B', 10), ('C', 8)):
        ws4.column_dimensions[col].width = w
    for c in range(4, 4 + len(METRICS)):
        ws4.column_dimensions[openpyxl.utils.get_column_letter(c)].width = 18
    ws4.freeze_panes = 'D2'

    out = Path(args.out) if args.out else d / 'statistics_avg_all.xlsx'
    wb.save(out)

    # -------------------------------------------------------------- console
    print('=== all groups (failed tasks counted at cap = {}), {} group(s) from {} ==='
          .format(args.max_retries, len(data), d))
    hdr = '{:<18s}{:<9s}{:>4s} | '.format('model', 'baseline', 'run') + ' | '.join(
        '{:>14s}'.format(l) for _k, l, _d in CONSOLE_KEYS)
    print(hdr)
    print('-' * len(hdr))
    for model, variant, runs in data:
        cells = []
        for key, _l, dec in CONSOLE_KEYS:
            vals = [r[key] for r in runs if r.get(key) is not None]
            cells.append('{:>14s}'.format(_ms(vals, dec)[0] if vals else '-'))
        print('{:<18s}{:<9s}{:>4d} | '.format(model, variant, len(runs))
              + ' | '.join(cells))
    print('\n(* calls/task: failed tasks counted at the call cap)')
    print('wrote {}  (sheets: summary / mean / std / per_run)'.format(out))


if __name__ == '__main__':
    main()
