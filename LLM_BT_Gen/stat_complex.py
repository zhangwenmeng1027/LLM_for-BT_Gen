# -*- coding: utf-8 -*-
"""Aggregate statistics for the 10-task COMPLEX benchmark (results_complex/).

Reuses the two general statistics scripts on the complex results dir:
  - stat_avg_all.py : the 3x3 paper table, per (model x baseline) group,
    every metric as mean +/- std over the run files, into ONE xlsx with
    sheets summary / mean / std / per_run
  - stats_avg.py    : the per-group averages plus the per_task sheet
    (task difficulty: how often each of the 10 tasks is solved)

Usage:
  python stat_complex.py                       # both, --last 5 (5-run protocol)
  python stat_complex.py --last 3              # average only the newest 3 runs
  python stat_complex.py --no-summary          # skip the console 3x3 table
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, 'results_complex')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--results_dir', default=RESULTS)
    ap.add_argument('--last', type=int, default=5,
                    help='per group, average only the newest N run files '
                         '(default 5 = the 5-repeat protocol; 0 = all runs)')
    ap.add_argument('--max-retries', type=int, default=None,
                    help='call cap failed tasks count at (default 10)')
    ap.add_argument('--no-summary', action='store_true',
                    help='skip stat_avg_all.py (console table + paper xlsx)')
    args = ap.parse_args()

    if not os.path.isdir(args.results_dir):
        sys.exit('no results dir: {} (run run_complex.py first)'.format(
            args.results_dir))
    last = args.last or None

    if not args.no_summary:
        cmd = [sys.executable, os.path.join(HERE, 'stat_avg_all.py'),
               '--dir', args.results_dir]
        if last:
            cmd += ['--last', str(last)]
        if args.max_retries:
            cmd += ['--max-retries', str(args.max_retries)]
        out = os.path.join(args.results_dir, 'statistics_complex.xlsx')
        cmd += ['--out', out]
        print('=== 3x3 paper table (mean +/- std) ===')
        subprocess.call(cmd)
        print()

    print('=== per-group averages + per-task difficulty ===')
    cmd = [sys.executable, os.path.join(HERE, 'stats_avg.py'),
           '--results_dir', args.results_dir]
    if last:
        cmd += ['--last', str(last)]
    subprocess.call(cmd)


if __name__ == '__main__':
    main()
