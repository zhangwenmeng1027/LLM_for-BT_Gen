# -*- coding: utf-8 -*-
"""Run the HARD 70-task benchmark (Behaverify_benchmark_hard.xlsx) with every
(baseline x model) combination.  Thin driver around llm_bt_gen.py, mirroring
run_complex.py: results go to results_hard/ so they never mix with the
original benchmark (results/) or the complex tasks (results_complex/).

Run numbering continues automatically: existing summary files are detected,
so re-launching a combination appends the missing repetitions (_4, _5, ...)
instead of overwriting anything.

Usage:
  python run_hard.py                                  # 3 models x 3 baselines x 5 reps
  python run_hard.py --models gpt-4o --baselines noce --repeat 2
  python run_hard.py --models gpt-5.5,claude-opus-4-6 --baselines noce --repeat 5
  python run_hard.py --repeat 1                       # single-rep pilot
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BENCHMARK = os.path.join(HERE, '..', 'behaverify', 'Benchmark',
                         'Behaverify_benchmark_hard.xlsx')
RESULTS = os.path.join(HERE, 'results_hard')

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

    if not os.path.exists(BENCHMARK):
        sys.exit('hard benchmark not found: {} (run make_hard_benchmark.py '
                 'first)'.format(BENCHMARK))
    models = [m.strip() for m in args.models.split(',') if m.strip()]
    baselines = [b.strip() for b in args.baselines.split(',') if b.strip()]
    os.makedirs(RESULTS, exist_ok=True)

    combos = [(m, b) for m in models for b in baselines]
    print('hard benchmark: {} model(s) x {} baseline(s) x {} repeat(s) '
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
          'python stat_avg_all.py --dir {} --last 5'.format(
              len(combos), time.time() - t0, RESULTS))


if __name__ == '__main__':
    main()
