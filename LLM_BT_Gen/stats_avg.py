# -*- coding: utf-8 -*-
"""
Detailed per-model averages over the summary files in results/ (stats.py 的
论文口径补充版：平均值 + 费用 + 时间分解 + 每任务难度表).

Runs are grouped by model (+baseline, shown as "<model> [<baseline>]", same
grouping as stats.py).  For each group, averaged over that group's runs:

  Avg Solved / Solve %        平均成功任务数 / 平均解决率
  Calls/Task*                 每任务平均 LLM 调用次数；失败任务按该次运行的调用
                              上限 max_rounds 计（"含放弃成本"的口径, * 标记）
  Calls/Solved                仅统计成功任务的平均调用次数（修复效率）
  Tokens/Task                 每任务平均总 token 数（失败任务也计入）
  Cost/Run $                  跑完一整遍 benchmark（如 70 个任务）的平均花费
  Cost/Task $                 每任务平均花费
  Time/Solved s               解决一个任务的平均总耗时（仅成功任务）
  Time/Task s                 每任务平均总耗时（失败任务也计入）
  LLM s/Task                  每任务平均 LLM 调用耗时
  Verify s/Task               每任务平均验证器耗时

Cost columns are 'n/a' when any task lacks a price (e.g. gpt-5.5 without a
"prices" entry in llm_config.json); time columns are 'n/a' for old-format
files that did not record them.  A second xlsx sheet 'per_task' lists, per
task and group: solve frequency across runs, avg calls (failed=limit), avg
tokens and the three time columns -- useful for task-difficulty analysis.

Usage:
  python stats_avg.py                                # all models & baselines
  python stats_avg.py --last 5                       # per group: newest 5 files only
  python stats_avg.py --model gpt-4o                 # one model (all baselines)
  python stats_avg.py --model gpt-4o --baseline full # one model + baseline
  python stats_avg.py --out results/result_avg.xlsx
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

# summary sheet: (header, key); * = failed tasks count as the call limit
COLS = [('Model', 'model'),
        ('Runs', 'runs'),
        ('Tasks/Run', 'tasks_per_run'),
        ('Avg Solved', 'avg_solved'),
        ('Solve %', 'solve_rate'),
        ('Calls/Task*', 'avg_calls_task'),
        ('Calls/Solved', 'avg_calls_solved'),
        ('Tokens/Task', 'avg_tokens_task'),
        ('Cost/Run $', 'avg_cost_run'),
        ('Cost/Task $', 'avg_cost_task'),
        ('Time/Solved s', 'avg_time_solved'),
        ('Time/Task s', 'avg_time_task'),
        ('LLM s/Task', 'avg_llm_task'),
        ('Verify s/Task', 'avg_verify_task')]

TASK_HEADERS = ['Model', 'Task', 'Solved/Runs', 'Rate %', 'Calls*', 'Tokens',
                'Time s', 'LLM s', 'Verify s']


def run_sort_key(path):
    """Sort by (stem, run number) so _10 comes after _9, not after _1."""
    m = FILENAME_RE.search(os.path.basename(path))
    if m:
        return (m.group(1), int(m.group(2)))
    return (os.path.basename(path), 0)


def load_runs(results_dir, model=None, baseline=None):
    """[(group_key, max_rounds, task_records)] for every readable summary file,
    in run order.  group_key = model, or "<model> [<baseline>]" for non-full
    baselines so baselines never mix with the main method."""
    runs = []
    paths = sorted(glob.glob(os.path.join(results_dir, 'summary*.json')),
                   key=run_sort_key)
    for path in paths:
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print('skipping unreadable {}: {}'.format(path, e))
            continue
        mdl = data.get('model')
        if not mdl:                                   # fall back to file name
            m = FILENAME_RE.search(os.path.basename(path))
            mdl = m.group(1) if m else os.path.basename(path)
        bl = data.get('baseline') or 'full'
        key = mdl if bl == 'full' else '{} [{}]'.format(mdl, bl)
        if model and mdl != model:
            continue
        if baseline and bl != baseline:
            continue
        tasks = data.get('results') or []
        if tasks:
            runs.append((key, data.get('max_rounds') or 5, tasks))
    return runs


def num(v):
    """Pass through numbers, treat missing/None as None."""
    return v if isinstance(v, (int, float)) else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def calls_of(task, cap):
    """LLM calls of one task; FAILED tasks count as the fixed call cap
    (default 10, --max-retries)."""
    n = task.get('n_calls')
    if n is None:                                    # older files store rounds
        n = task.get('rounds') or 0
    if not task.get('success'):
        n = max(n, cap)
    return n


def group_stats(key, runs, cap):
    """Aggregate one group's runs ((max_rounds, tasks) pairs) into COLS values."""
    n_runs = len(runs)
    total = sum(len(ts) for _, ts in runs)
    solved = sum(1 for _, ts in runs for t in ts if t.get('success'))
    calls_all, calls_ok = [], []
    tokens_all, time_all, time_ok, llm_all, ver_all = [], [], [], [], []
    cost_tot, cost_missing = 0.0, 0
    for mr, tasks in runs:
        for t in tasks:
            ok = bool(t.get('success'))
            c = calls_of(t, cap)
            calls_all.append(c)
            if ok:
                calls_ok.append(c)
                time_ok.append(num(t.get('time_s')))
            tokens_all.append(num(t.get('total_tokens')))
            time_all.append(num(t.get('time_s')))
            llm_all.append(num(t.get('llm_time_s')))
            ver_all.append(num(t.get('verify_time_s')))
            cost = num(t.get('cost_usd'))
            if cost is None:
                cost_missing += 1                    # unpriced model -> n/a
            else:
                cost_tot += cost
    return {'model': key, 'runs': n_runs,
            'tasks_per_run': round(total / n_runs, 1),
            'avg_solved': round(solved / n_runs, 1),
            'solve_rate': round(100.0 * solved / total, 1) if total else 0.0,
            'avg_calls_task': mean(calls_all),
            'avg_calls_solved': mean(calls_ok),
            'avg_tokens_task': mean(tokens_all),
            'avg_cost_run': (None if cost_missing else round(cost_tot / n_runs, 4)),
            'avg_cost_task': (None if cost_missing else round(cost_tot / total, 6)),
            'avg_time_solved': mean(time_ok),
            'avg_time_task': mean(time_all),
            'avg_llm_task': mean(llm_all),
            'avg_verify_task': mean(ver_all)}


def per_task_rows(runs, cap):
    """One row per (group, task): solve frequency and averages across runs."""
    agg = {}
    for key, mr, tasks in runs:
        for t in tasks:
            a = agg.setdefault((key, t.get('task', '?')),
                               {'n': 0, 'ok': 0, 'calls': [], 'tokens': [],
                                'time': [], 'llm': [], 'ver': []})
            a['n'] += 1
            a['ok'] += 1 if t.get('success') else 0
            a['calls'].append(calls_of(t, cap))
            a['tokens'].append(num(t.get('total_tokens')))
            a['time'].append(num(t.get('time_s')))
            a['llm'].append(num(t.get('llm_time_s')))
            a['ver'].append(num(t.get('verify_time_s')))
    rows = []
    for (key, task), a in sorted(agg.items()):
        rows.append([key, task, '{}/{}'.format(a['ok'], a['n']),
                     round(100.0 * a['ok'] / a['n'], 1),
                     mean(a['calls']), mean(a['tokens']), mean(a['time']),
                     mean(a['llm']), mean(a['ver'])])
    return rows


def fmt(v, money=False, pct=False):
    if v is None:
        return 'n/a'
    if money:
        return '${:.4f}'.format(v)
    if pct:
        return '{:.0f}%'.format(v)
    return '{}'.format(v)


def print_table(stats):
    header = [h for h, _ in COLS]
    rows = [[fmt(s[k], money=k.startswith('avg_cost'), pct=k == 'solve_rate')
             for _, k in COLS] for s in stats]
    widths = [max(len(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    for i, r in enumerate([header] + rows):
        print('  '.join(str(v).ljust(w) for v, w in zip(r, widths)))
        if i == 0:
            print('-' * (sum(widths) + 2 * (len(widths) - 1)))
    print('\n(* Calls/Task: failed tasks count as the fixed call cap of 10 '
          '(--max-retries to change); n/a = missing data, e.g. no price '
          'configured for the model or old-format files without time fields)')


def write_xlsx(stats, task_rows, out_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'summary'
    ws.append([h for h, _ in COLS])
    for s in stats:
        ws.append([s[k] for _, k in COLS])
    wt = wb.create_sheet('per_task')
    wt.append(TASK_HEADERS)
    for r in task_rows:
        wt.append(r)
    wb.save(out_path)


def main():
    ap = argparse.ArgumentParser(description='average per-model statistics '
                                             'over summary*.json (detailed)')
    ap.add_argument('--results_dir', default=DEFAULT_RESULTS)
    ap.add_argument('--model', default=None,
                    help='restrict to this model (baselines stay separate groups)')
    ap.add_argument('--baseline', choices=['full', 'noce', 'withbt'], default=None,
                    help='restrict to this baseline')
    ap.add_argument('--last', type=int, default=None,
                    help='per group, average only the newest N summary files '
                         '(e.g. --last 5 for the 5-repeat protocol)')
    ap.add_argument('--max-retries', type=int, default=10,
                    help='fixed call cap failed tasks count at in Calls/Task* '
                         '(default 10)')
    ap.add_argument('--out', default=None,
                    help='output xlsx (default <results_dir>/result_avg.xlsx)')
    args = ap.parse_args()

    runs = load_runs(args.results_dir, args.model, args.baseline)
    if not runs:
        sys.exit('no matching summary*.json found in ' + args.results_dir)

    groups = {}
    for key, mr, tasks in runs:
        groups.setdefault(key, []).append((mr, tasks))
    if args.last:
        groups = {k: rs[-args.last:] for k, rs in groups.items()}
    stats = [group_stats(k, rs, args.max_retries) for k, rs in sorted(groups.items())]

    print('average statistics by model ({} group(s), {} runs, from {})\n'.format(
        len(stats), sum(s['runs'] for s in stats), args.results_dir))
    print_table(stats)

    out = args.out or os.path.join(args.results_dir, 'result_avg.xlsx')
    write_xlsx(stats, per_task_rows(runs, args.max_retries), out)
    print('\nstats written to {} (sheet "summary" + per-task sheet "per_task")'.format(out))


if __name__ == '__main__':
    main()
