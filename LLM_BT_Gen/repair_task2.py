# -*- coding: utf-8 -*-
"""repair_task.py 的并行副本：流程完全相同，但走第二条 API 通道。

通道来源（llm_config.json）：
  "api_key2":  第二个 API key
  "base_url2": 第二个接口域名（如 https://4sapi.org）
注入方式：子进程环境变量 LLM_API_KEY / LLM_BASE_URL（llm_bt_gen.py 中环境
变量优先于 keys 前缀匹配与 base_url 配置），并设 LLM_PROXY='' 直连——
4sapi.org 可直连，因此第二条链路完全不依赖本地代理。

与 repair_task.py 的差异：
  * 注入 LLM_API_KEY=api_key2、LLM_BASE_URL=base_url2、LLM_PROXY=''（直连）
  * 临时文件名 _repair2_tmp.json（两脚本可同时运行互不干扰）

并行注意：两个脚本可同时跑，但不要同时修【同一 baseline 的轮次】——
full/noce/withbt 各自的任务目录独立（results_hard/<task>/、noce/<task>/、
withbt/<task>/），按 baseline 分工即可安全并行，例如：
  终端 A: python repair_task.py  --round summary_gpt-5.5_1       --results_dir results_hard
  终端 B: python repair_task2.py --round summary_gpt-5.5_withbt_2 --results_dir results_hard

Usage 与 repair_task.py 完全一致：
  python repair_task2.py --round summary_gpt-5.5_1 --results_dir results_hard
  python repair_task2.py --model gpt-5.5 --results_dir results_hard
  python repair_task2.py --round ... --dry-run
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
CONFIG_FILE = os.path.join(HERE, 'llm_config.json')
DIRS = {'results_complex': os.path.join(HERE, 'complex_tasks.xlsx'),
        'results_hard': os.path.join(HERE, '..', 'behaverify', 'Benchmark',
                                     'Behaverify_benchmark_hard.xlsx')}
BASELINE_ORDER = {'full': 0, 'noce': 1, 'withbt': 2}


def second_channel():
    """(key, base_url) of the second API channel from llm_config.json
    ("api_key2" / "base_url2"), or exit with instructions when missing."""
    with open(CONFIG_FILE, encoding='utf-8') as f:
        cfg = json.load(f)
    key = (cfg.get('api_key2') or '').strip()
    url = (cfg.get('base_url2') or '').strip()
    if not key or not url:
        sys.exit('llm_config.json 缺少第二通道配置 -- 请在 {} 中填好 '
                 '"api_key2": "sk-..." 和 "base_url2": "https://..." '
                 '后重试'.format(CONFIG_FILE))
    return key, url


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


def round_stems(results_dir, model, baselines=None):
    """Round file stems of one model in run order (baseline, then number);
    baselines = optional set to keep only those (for --model mode)."""
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
        if name == model and (not baselines or base in baselines):
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

    env = dict(os.environ)
    if not mock:
        key, base_url = second_channel()
        env['LLM_API_KEY'] = key            # env beats prefix matching
        env['LLM_BASE_URL'] = base_url      # second endpoint, e.g. 4sapi.org
        env['LLM_PROXY'] = ''               # direct connection (org needs no proxy)
        print('  channel #2: {}  key ***{}  (direct, no proxy)'.format(
            base_url, key[-6:]))
    tmp = os.path.join(results_dir, '_repair2_tmp.json')
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
    rc = subprocess.call(cmd, env=env)
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
    ap.add_argument('--baseline', default=None,
                    help='with --model: comma separated baselines to process '
                         '(e.g. withbt) -- lets two terminals split the work '
                         'by baseline so task dirs never collide')
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
    baselines = ({b.strip() for b in args.baseline.split(',') if b.strip()}
                 if args.baseline else None)

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
            stems = round_stems(results_dir, args.model, baselines)
        else:
            for d, b in DIRS.items():          # first dir holding the model
                stems = round_stems(os.path.join(HERE, d), args.model, baselines)
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
