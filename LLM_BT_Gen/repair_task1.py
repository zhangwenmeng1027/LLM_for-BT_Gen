# -*- coding: utf-8 -*-
"""Repair tasks inside EXISTING summary rounds: re-run only the tasks whose
record is missing or invalid, SKIP the ones already recorded, and merge the
fresh records back into the round's json + xlsx (other tasks untouched).

A task counts as ALREADY RECORDED (skipped) when it has a valid record:
  * success with sane token usage (prompt tokens >= 500; values like 12/24
    are relay accounting garbage), or
  * a genuine verification failure ("not verified within N rounds") -- a real
    experimental outcome, NOT missing data.  (The relay reports prompt tokens
    in two legitimate scales -- full prompt vs non-cached tail only -- so
    prompt-size variance alone is NOT treated as bad data.)
A task is (re-)run when it failed with an LLM/network error, its usage count
is absurd, or it has NO record at all (row deleted / never run).  Finished
work is always skipped, so commands are idempotent and safe to re-launch
after an interruption.

The results dir and benchmark are auto-detected from the round file's
location: results_complex -> complex_tasks.xlsx, results_hard -> the hard
benchmark xlsx; pass --results_dir/--benchmark to override.

Usage:
  python repair_task.py --round summary_gpt-5.5_1            # one round
  python repair_task.py --round summary_gpt-5.5_1 --dry-run  # plan only
  python repair_task.py --model gpt-5.5                       # every round of
                                                              # that model that
                                                              # has pending
                                                              # tasks, one
                                                              # after another
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DIRS = {'results_complex': os.path.join(HERE, 'complex_tasks.xlsx'),
        'results_hard': os.path.join(HERE, '..', 'behaverify', 'Benchmark',
                                     'Behaverify_benchmark_hard.xlsx')}
BASELINE_ORDER = {'full': 0, 'noce': 1, 'withbt': 2}


def benchmark_tasks(path):
    """Task names from the benchmark xlsx ('benchmark' sheet, column A)."""
    import openpyxl
    ws = openpyxl.load_workbook(path)['benchmark']
    return [str(r[0]).strip() for r in ws.iter_rows(min_row=2, values_only=True) if r[0]]


def invalid_reason(rec):
    """None when the record is valid (skip), else a short why-string."""
    if rec.get('success'):
        p = rec.get('prompt_tokens')
        if p is not None and p < 500:
            return 'prompt={} (bogus usage)'.format(p)
        return None
    if 'LLM error' in (rec.get('reason') or ''):
        return 'network error: ' + (rec.get('reason') or '')[:40]
    return None                       # genuine verify failure = valid result


def locate_round(stem):
    """(results_dir, benchmark) of the dir holding <stem>.json; exits when
    missing, or when the stem exists in SEVERAL dirs (ambiguous -- name the
    dir explicitly with --results_dir)."""
    hits = [(d, b) for d, b in DIRS.items()
            if os.path.exists(os.path.join(HERE, d, stem + '.json'))]
    if not hits:
        sys.exit('no {}.json in {}'.format(stem, ' / '.join(DIRS)))
    if len(hits) > 1:
        sys.exit("'{}' exists in both {} -- pass --results_dir to pick one"
                 .format(stem, ' and '.join(h[0] for h in hits)))
    return os.path.join(HERE, hits[0][0]), hits[0][1]


def round_stems(results_dir, model):
    """Round file stems of one model in run order (baseline, then number)."""
    out = []
    for f in glob.glob(os.path.join(results_dir, 'summary_*.json')):
        m = re.match(r'summary_(.*)_(\d+)$', os.path.basename(f)[:-5])
        if not m:
            continue
        name, n = m.group(1), int(m.group(2))
        base = 'full'
        for suf in ('_noce', '_withbt'):
            if name.endswith(suf):
                name, base = name[:-len(suf)], suf[1:]
        if name == model:
            out.append((BASELINE_ORDER.get(base, 9), n, os.path.basename(f)[:-5]))
    return [s for _b, _n, s in sorted(out)]


def process_round(stem, results_dir, benchmark, only=None, force=False,
                  dry=False, mock=False, attempts=20, retry_wait=1.0):
    jpath = os.path.join(results_dir, stem + '.json')
    xpath = os.path.join(results_dir, stem + '.xlsx')
    with open(jpath, encoding='utf-8') as f:
        data = json.load(f)
    model = data['model']
    baseline = data.get('baseline', 'full')
    max_rounds = data.get('max_rounds', 5)
    only = {t.strip() for t in only.split(',') if t.strip()} if only else None

    rec_of = {r['task']: r for r in data['results']}
    bench = benchmark_tasks(benchmark)
    todo, skipped = [], []
    for name in bench:                       # benchmark order = run order
        if only is not None and name not in only:
            continue
        r = rec_of.get(name)
        if r is None:
            todo.append((name, 'no record yet (row missing)'))
        else:
            why = invalid_reason(r)
            if force or why:
                todo.append((name, why or 'forced re-run'))
            else:
                skipped.append((name, why))

    print('\n==== {}  (model {}, baseline {}, max_rounds {}) ===='.format(
        stem, model, baseline, max_rounds))
    print('  {} recorded / {} to run'.format(len(skipped), len(todo)))
    if not todo:
        print('  nothing to do: every task already recorded')
        return
    for t, why in todo:
        print('  RUN   {}  ({})'.format(t, why))
    if dry:
        return

    tmp = os.path.join(results_dir, '_repair_tmp.json')
    cmd = [sys.executable, os.path.join(HERE, 'llm_bt_gen.py'),
           '--tasks', ','.join(t for t, _ in todo),
           '--benchmark', benchmark,
           '--results_dir', results_dir,
           '--baseline', baseline,
           '--model', model,
           '--repeat', '1',
           '--max_rounds', str(max_rounds),
           '--out', tmp,
           '--xlsx', xpath,
           '--llm_attempts', str(attempts),
           '--llm_retry_wait', str(retry_wait)]
    if mock:
        cmd.append('--mock')
    t0 = time.time()
    rc = subprocess.call(cmd)
    if rc != 0 or not os.path.exists(tmp):
        sys.exit('re-run failed (exit code {}), round files untouched'.format(rc))

    with open(tmp, encoding='utf-8') as f:
        fresh = json.load(f)['results']
    fresh_of = {r['task']: r for r in fresh}
    for r in data['results']:
        if r['task'] in fresh_of:
            r.update(fresh_of[r['task']])
            if r['success']:
                r.pop('reason', None)    # drop stale placeholder/failure reason
    have = {r['task'] for r in data['results']}
    data['results'].extend(r for r in fresh if r['task'] not in have)
    with open(jpath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.remove(tmp)

    ok = sum(1 for r in fresh if r['success'])
    print('  repaired {} task(s) in {:.1f}s ({} succeeded)'.format(
        len(fresh), time.time() - t0, ok))
    print('  updated: {}\n           {} (rows merged by task name)'.format(jpath, xpath))


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--round', help='round file stem, e.g. summary_gpt-5.5_1')
    g.add_argument('--model', help='repair EVERY round of this model that '
                                   'has pending tasks (in run order)')
    ap.add_argument('--tasks', default=None,
                    help='only consider these task names (comma separated); '
                         'valid records are still skipped unless --force')
    ap.add_argument('--force', action='store_true',
                    help='re-run even tasks with a valid record')
    ap.add_argument('--dry-run', action='store_true',
                    help='show the plan (run / skip) without calling the LLM')
    ap.add_argument('--mock', action='store_true',
                    help='offline re-run (llm_bt_gen canned responses, no API)')
    ap.add_argument('--llm_attempts', type=int, default=20,
                    help='max attempts per LLM call before giving up '
                         '(default %(default)s)')
    ap.add_argument('--llm_retry_wait', type=float, default=1.0,
                    help='seconds to wait before retrying a failed LLM call '
                         '(default %(default)s)')
    ap.add_argument('--benchmark', default=None,
                    help='default: auto from the results dir')
    ap.add_argument('--results_dir', default=None,
                    help='default: auto-detected from the round file name')
    args = ap.parse_args()

    if args.round:
        if args.results_dir:
            results_dir = os.path.abspath(args.results_dir)
            key = os.path.basename(os.path.normpath(results_dir))
            benchmark = args.benchmark or DIRS.get(key)
            if not benchmark:
                sys.exit('unknown results dir {} -- pass --benchmark'.format(key))
        else:
            results_dir, benchmark = locate_round(args.round)
            if args.benchmark:
                benchmark = args.benchmark
        process_round(args.round, results_dir, benchmark,
                      args.tasks, args.force, args.dry_run, args.mock,
                      args.llm_attempts, args.llm_retry_wait)
    else:
        stems = None
        if args.results_dir:
            results_dir = os.path.abspath(args.results_dir)
            key = os.path.basename(os.path.normpath(results_dir))
            benchmark = args.benchmark or DIRS.get(key)
            if not benchmark:
                sys.exit('unknown results dir {} -- pass --benchmark'.format(key))
            stems = round_stems(results_dir, args.model)
        else:
            for d, b in DIRS.items():          # first dir holding the model
                stems = round_stems(os.path.join(HERE, d), args.model)
                if stems:
                    results_dir, benchmark = os.path.join(HERE, d), b
                    break
        if not stems:
            sys.exit('no rounds for model {} found'.format(args.model))
        print('model {} in {}: {} round(s)'.format(
            args.model, os.path.basename(results_dir), len(stems)))
        for stem in stems:
            process_round(stem, results_dir, benchmark,
                          args.tasks, args.force, args.dry_run, args.mock,
                          args.llm_attempts, args.llm_retry_wait)


if __name__ == '__main__':
    main()
