# -*- coding: utf-8 -*-
"""
Statistics over the summary files in results/, grouped by LLM model.

Every llm_bt_gen.py run stores results/summary_<model>_<N>.json (full
baseline) or results/summary_<model>_<baseline>_<N>.json; baseline runs are
grouped as "<model> [<baseline>]" so they never mix with the full method
(legacy summary*.json files work too: the model is read from the file itself).
For each model, averaged over that model's runs, this script reports:
  - tasks per run and solved tasks (average count and percentage)
  - tasks solved with exactly 1 LLM call   (average count, % of solved)
  - tasks solved with exactly 2 LLM calls  (average count, % of solved)
  - tasks solved with 3 or more LLM calls  (average count, % of solved)
Results are printed to the console and written to result.xlsx.

Usage:
  python stats.py                                  # scan ./results
  python stats.py --results_dir results --out result.xlsx
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RESULTS = os.path.join(HERE, 'results')

FILENAME_RE = re.compile(r'summary_(.+)_(\d+)\.json$')

# xlsx column order: (header, key) -- numeric percentages are stored as numbers
COLS = [('Model', 'model'),
        ('Runs', 'runs'),
        ('Avg Tasks/Run', 'avg_tasks'),
        ('Avg Solved', 'avg_solved'),
        ('Solve Rate %', 'solve_rate'),
        ('Avg 1-Call', 'avg_1call'), ('1-Call % of Solved', 'pct_1call'),
        ('Avg 2-Call', 'avg_2call'), ('2-Call % of Solved', 'pct_2call'),
        ('Avg 3+-Call', 'avg_3call'), ('3+-Call % of Solved', 'pct_3call')]


def load_runs(results_dir):
    """Return {model: [run, ...]} where each run is the list of task records."""
    model_runs = {}
    for path in sorted(glob.glob(os.path.join(results_dir, 'summary*.json'))):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print('skipping unreadable {}: {}'.format(path, e))
            continue
        model = data.get('model')
        if not model:                                   # fall back to file name
            m = FILENAME_RE.search(os.path.basename(path))
            model = m.group(1) if m else os.path.basename(path)
        baseline = data.get('baseline')
        if baseline and baseline != 'full':             # keep 'full' grouped with legacy runs
            model = '{} [{}]'.format(model, baseline)
        tasks = data.get('results') or []
        if tasks:
            model_runs.setdefault(model, []).append(tasks)
    return model_runs


def n_calls_of(task):
    """LLM calls used for a task (older files only store rounds)."""
    n = task.get('n_calls')
    return n if n is not None else task.get('rounds')


def model_stats(model, runs):
    """Aggregate one model's runs into the reported metrics."""
    n_runs = len(runs)
    total = sum(len(run) for run in runs)
    solved = [t for run in runs for t in run if t.get('success')]
    n_solved = len(solved)

    def pct(part, whole):
        return round(100.0 * part / whole, 1) if whole else 0.0

    n1 = sum(1 for t in solved if n_calls_of(t) == 1)
    n2 = sum(1 for t in solved if n_calls_of(t) == 2)
    n3 = sum(1 for t in solved if (n_calls_of(t) or 0) >= 3)
    return {'model': model, 'runs': n_runs,
            'avg_tasks': round(total / n_runs, 1), 'avg_solved': round(n_solved / n_runs, 1),
            'solve_rate': pct(n_solved, total),
            'avg_1call': round(n1 / n_runs, 1), 'pct_1call': pct(n1, n_solved),
            'avg_2call': round(n2 / n_runs, 1), 'pct_2call': pct(n2, n_solved),
            'avg_3call': round(n3 / n_runs, 1), 'pct_3call': pct(n3, n_solved)}


def print_table(stats):
    header = ['Model', 'Runs', 'Task/Run', 'Solved', 'Solve%',
              '1call', '1call%', '2call', '2call%', '3+call', '3+call%']
    rows = [[s['model'], s['runs'], s['avg_tasks'], s['avg_solved'],
             '{:.0f}%'.format(s['solve_rate']),
             s['avg_1call'], '{:.0f}%'.format(s['pct_1call']),
             s['avg_2call'], '{:.0f}%'.format(s['pct_2call']),
             s['avg_3call'], '{:.0f}%'.format(s['pct_3call'])] for s in stats]
    widths = [max(len(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    for i, r in enumerate([header] + rows):
        line = '  '.join(str(v).ljust(w) for v, w in zip(r, widths))
        print(line)
        if i == 0:
            print('-' * len(line))


def write_xlsx(stats, out_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'stats'
    ws.append([h for h, _ in COLS])
    for s in stats:
        ws.append([s[k] for _, k in COLS])
    wb.save(out_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument('--results_dir', default=DEFAULT_RESULTS)
    ap.add_argument('--out', default=None,
                    help='output xlsx path (default <results_dir>/result.xlsx)')
    args = ap.parse_args()

    model_runs = load_runs(args.results_dir)
    if not model_runs:
        sys.exit('no summary*.json with results found in ' + args.results_dir)
    stats = [model_stats(m, rs) for m, rs in sorted(model_runs.items())]

    print('summary statistics by model ({} models, from {})\n'.format(
        len(stats), args.results_dir))
    print_table(stats)

    out = args.out or os.path.join(args.results_dir, 'result.xlsx')
    write_xlsx(stats, out)
    print('\nstats written to', out)


if __name__ == '__main__':
    main()
