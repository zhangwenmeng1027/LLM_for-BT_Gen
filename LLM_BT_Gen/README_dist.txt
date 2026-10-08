BTRun -- Portable LLM-to-Behavior-Tree Benchmark Runner
========================================================

WHAT THIS IS
------------
A self-contained Windows executable that runs the complete BT-synthesis
experiment:

  * benchmark suites : HARD (70 tasks) and COMPLEX (10 tasks)
  * models           : gpt-4o, gpt-5.5, claude-opus-4-6
  * baselines        : full (verifier feedback), withbt, noce
  * CEGIS loop       : LLM generates a BehaVerify .tree -> behaverify+NuSMV
                       verifies it -> feedback -> retry (up to 5 rounds)

Everything (Python runtime, behaverify, NuSMV, benchmarks, prompt) is inside
this folder.  No Python, venv or NuSMV installation is needed on the target
machine.  Copy the WHOLE folder to any Windows x64 machine and run BTRun.exe.

The LLM API (https://4sapi.org) is always contacted DIRECTLY -- no proxy is
used, regardless of any system proxy settings.  API keys for the GPT and
Claude models are embedded in the executable.

FOLDER LAYOUT
-------------
  BTRun.exe                 the program (run it from a terminal, not by
                            double-click, so you see progress and can stop
                            with Ctrl+C)
  _internal\                PyInstaller runtime (do not modify)
  NuSMV\bin\NuSMV.exe       model checker used by the verifier
  benchmarks\               Behaverify_benchmark_hard.xlsx (70 tasks),
                            complex_tasks.xlsx (10 tasks)
  prompt_behaverify.txt     the few-shot prompt (editable)
  selftest\selftest.tree    reference tree for --selftest
  llm_config.json           OPTIONAL override file (see below)
  results_hard\             created at runtime: summaries + per-task trees
  results_complex\          created at runtime

QUICK START
-----------
  1. Open a terminal (cmd or PowerShell) in this folder.
  2. Check the toolchain first (no API cost):
         BTRun.exe --selftest
  3. Optionally check the live LLM connection (one tiny API call):
         BTRun.exe --selftest --api
  4. Run the FULL experiment (default: both suites, 3 models x 3 baselines
     x 5 repeats, three worker processes in parallel -- one per model):
         BTRun.exe

COMMANDS
--------
  BTRun.exe
      Full default experiment: suites hard+complex, all 3 models, all 3
      baselines, 5 repeats each.  Models run in PARALLEL (one worker per
      model; inside a worker the baselines run one after another).

  BTRun.exe --parallel baselines
      Same experiment but parallelized across the three baselines instead
      (one worker per baseline; inside a worker the models run in sequence).

  BTRun.exe --parallel none
      Everything sequentially in one process.

  BTRun.exe --suite hard          # only the 70 hard tasks
  BTRun.exe --suite complex       # only the 10 complex tasks
  BTRun.exe --suite both          # both (default)

  BTRun.exe --models gpt-4o,gpt-5.5,claude-opus-4-6     (default: all three)
  BTRun.exe --baselines full,noce,withbt                (default: all three)
  BTRun.exe --repeat 5            # repeats per (suite x model x baseline)
  BTRun.exe --max_rounds 5        # LLM call cap per task

  Pilot / smoke tests:
  BTRun.exe --repeat 1                        # one repetition only
  BTRun.exe --limit 5                         # only the first 5 tasks/suite
  BTRun.exe --tasks ABC3,CX1_deep_delivery    # only named tasks

  Other options:
  BTRun.exe --results_root D:\somewhere       # move output elsewhere
  BTRun.exe --llm_attempts 6 --llm_retry_wait 5

RESULTS
-------
Per run (one run = suite x model x baseline x repetition):
  results_hard\summary_<model>[_<baseline>]_<N>.json   per-task statistics
  results_hard\summary_<model>[_<baseline>]_<N>.xlsx   same, as a table
  results_complex\...                                  same for the complex suite
N increases with every finished repetition (_1, _2, ...), so re-launching a
crashed or interrupted combination APPENDS the missing repetitions instead
of overwriting anything.  Per-task candidate trees live under
  results_<suite>\<model>\[<baseline>\]<task>\round_*.tree and final.tree

Numbers reported per task: success, LLM call count, wall time, LLM time,
verify time, prompt/completion/total tokens, cost in USD.

NOTES
-----
* Only successful LLM responses consume a round; network errors (SSL,
  timeout, 5xx) are retried for free with a fixed wait.
* Failed attempts of the same (model, baseline) combination can simply be
  re-run; run numbering continues automatically.
* Optional llm_config.json next to BTRun.exe may override base_url, model,
  keys and prices.  A "proxy" entry in that file is IGNORED: this build
  always connects directly unless the environment variable LLM_PROXY is
  explicitly set.
* Stopping with Ctrl+C stops the workers; completed repetitions are already
  on disk.
* Windows SmartScreen may warn on first launch (unsigned binary);
  choose "More info" -> "Run anyway".
