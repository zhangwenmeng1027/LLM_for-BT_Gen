# -*- coding: utf-8 -*-
"""Run the 10-task COMPLEX benchmark with every (baseline x model) combination.

Thin driver around llm_bt_gen.py: for each model (outer) and baseline
(inner) it launches one llm_bt_gen.py run over complex_tasks.xlsx, writing
into results_complex/ so the results never mix with the main benchmark.
Summary files stack as
    results_complex/summary_<model>[_<baseline>]_<N>.json / .xlsx
with N continuing from previous runs, so re-launching a crashed/forgotten
combination simply appends the missing repetitions.

Each run stores the full per-task statistics (success, LLM calls, tokens,
cost, wall/LLM/verify time); aggregate them afterwards with stat_complex.py.

Usage:
  python run_complex.py                       # 3 models x 3 baselines x 5 reps
  python run_complex.py --repeat 1            # quick single pass (pilot)
  python run_complex.py --models gpt-4o,gpt-5.5
  python run_complex.py --baselines full,withbt
  python run_complex.py --max_rounds 5        # LLM call cap per task (default 5)
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BENCHMARK = os.path.join(HERE, 'complex_tasks.xlsx')
RESULTS = os.path.join(HERE, 'results_complex')

MODELS = ('gpt-4o', 'gpt-5.5', 'claude-opus-4-6')
BASELINES = ('full', 'noce', 'withbt')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', default=','.join(MODELS),
                    help='comma separated models (default: %(default)s)')
    ap.add_argument('--baselines', default=','.join(BASELINES),
                    help='comma separated baselines (default: %(default)s)')
    ap.add_argument('--repeat', type=int, default=5,
                    help='runs per (model, baseline) combination (default 5)')
    ap.add_argument('--max_rounds', type=int, default=5,
                    help='LLM call cap per task (default 5)')
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(',') if m.strip()]
    baselines = [b.strip() for b in args.baselines.split(',') if b.strip()]
    os.makedirs(RESULTS, exist_ok=True)

    combos = [(m, b) for m in models for b in baselines]
    print('complex benchmark: {} model(s) x {} baseline(s) x {} repeat(s) '
          '= {} runs, results in {}'.format(
              len(models), len(baselines), args.repeat, len(combos), RESULTS))

    t0 = time.time()
    for i, (model, baseline) in enumerate(combos, 1):
        print('\n############ [{}/{}] {} x {} x{} ############'.format(
            i, len(combos), model, baseline, args.repeat))
        cmd = [sys.executable, os.path.join(HERE, 'llm_bt_gen.py'),
               '--all',
               '--benchmark', BENCHMARK,
               '--results_dir', RESULTS,
               '--baseline', baseline,
               '--model', model,
               '--repeat', str(args.repeat),
               '--max_rounds', str(args.max_rounds)]
        rc = subprocess.call(cmd)
        if rc != 0:
            print('WARNING: {} x {} exited with code {} -- continuing with '
                  'the next combination'.format(model, baseline, rc))
    print('\nAll {} combination(s) finished in {:.1f}s.  Statistics: '
          'python stat_complex.py'.format(len(combos), time.time() - t0))


if __name__ == '__main__':
    main()
