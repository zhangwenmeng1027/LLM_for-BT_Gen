BTRun -- Portable LLM-to-Behavior-Tree Benchmark Runner (Linux x86_64)
=======================================================================

WHAT THIS IS
------------
A self-contained Linux executable that runs the complete BT-synthesis
experiment:

  * benchmark suites : HARD (70 tasks) and COMPLEX (10 tasks)
  * models           : gpt-4o, gpt-5.5, claude-opus-4-6
  * baselines        : full (verifier feedback), withbt, noce
  * CEGIS loop       : LLM generates a BehaVerify .tree -> behaverify+NuSMV
                       verifies it -> feedback -> retry (up to 10 rounds)

Everything (Python runtime, behaverify, NuSMV, benchmarks, prompt) is inside
this folder.  No Python, venv or NuSMV installation is needed on the target
machine.  Built on Ubuntu 22.04 (glibc 2.35): runs on Ubuntu 22.04 and any
newer release, and on other distributions with glibc >= 2.35.

The LLM API (https://4sapi.org) is always contacted DIRECTLY -- no proxy is
used, regardless of any system or environment proxy settings.  API keys for
the GPT and Claude models are embedded in the executable.

REQUIREMENTS
------------
  * Linux x86_64, glibc >= 2.35 (Ubuntu 22.04 or newer meets this)
  * ~1 GB free disk space for results during a full run
  * Outbound HTTPS to https://4sapi.org (direct internet access)
  * Nothing else -- no Python, no pip, no apt packages

FOLDER LAYOUT
-------------
  BTRun                    the program (executable; run it from a terminal)
  _internal/               PyInstaller runtime (do not modify)
  NuSMV/bin/NuSMV          model checker used by the verifier
  benchmarks/              Behaverify_benchmark_hard.xlsx (70 tasks),
                           complex_tasks.xlsx (10 tasks)
  prompt_behaverify.txt    the few-shot prompt (editable)
  selftest/selftest.tree   reference tree for --selftest
  llm_config.json          OPTIONAL override file (see below)
  results_hard/            created at runtime: summaries + per-task trees
  results_complex/         created at runtime

QUICK START
-----------
  1. Unpack ON THE LINUX MACHINE (the archive stores the +x permission):
         tar xzf BTRun-linux-x64.tar.gz
  2. Open a terminal in the unpacked folder.
  3. Check the toolchain first (no API cost):
         ./BTRun --selftest
  4. Optionally check the live LLM connection (one tiny API call):
         ./BTRun --selftest --api
  5. Run the FULL experiment (default: both suites, 3 models x 3 baselines
     x 5 repeats, three worker processes in parallel -- one per model):
         ./BTRun

If you copied the files out of the archive without tar (exec bit lost),
restore it once with:
     chmod +x BTRun NuSMV/bin/NuSMV NuSMV/bin/ltl2smv

COMMANDS
--------
  ./BTRun
      Full default experiment: suites hard+complex, all 3 models, all 3
      baselines, 5 repeats each.  Models run in PARALLEL (one worker per
      model; inside a worker the baselines run one after another).

  ./BTRun --parallel baselines
      Same experiment but parallelized across the three baselines instead
      (one worker per baseline; inside a worker the models run in sequence).

  ./BTRun --parallel none
      Everything sequentially in one process.

  ./BTRun --suite hard          # only the 70 hard tasks
  ./BTRun --suite complex       # only the 10 complex tasks
  ./BTRun --suite both          # both (default)

  ./BTRun --models gpt-4o,gpt-5.5,claude-opus-4-6     (default: all three)
  ./BTRun --baselines full,noce,withbt                (default: all three)
  ./BTRun --repeat 5            # repeats per (suite x model x baseline)
  ./BTRun --max_rounds 10       # LLM call cap per task (default 10)

  Pilot / smoke tests:
  ./BTRun --repeat 1                        # one repetition only
  ./BTRun --limit 5                         # only the first 5 tasks/suite
  ./BTRun --tasks ABC3,CX1_deep_delivery    # only named tasks

  Other options:
  ./BTRun --results_root /path/to/dir       # move output elsewhere
  ./BTRun --llm_attempts 30 --llm_retry_wait 1   # defaults: 30 tries, 1s wait

RESULTS
-------
Per run (one run = suite x model x baseline x repetition):
  results_hard/summary_<model>[_<baseline>]_<N>.json    per-task statistics
  results_hard/summary_<model>[_<baseline>]_<N>.xlsx    same, as a table
  results_complex/...                                   same for complex suite
N increases with every finished repetition (_1, _2, ...), so re-launching a
crashed or interrupted combination APPENDS the missing repetitions instead
of overwriting anything.  Per-task candidate trees live under
  results_<suite>/<model>/[<baseline>/]<task>/round_*.tree and final.tree

Numbers reported per task: success, LLM call count, wall time, LLM time,
verify time, prompt/completion/total tokens, cost in USD.

NOTES
-----
* Every baseline allows up to 10 LLM calls (rounds) per task by default
  (--max_rounds).
* Only successful LLM responses consume a round; transport-level errors
  (SSL, timeout, 5xx, connection reset) are retried automatically up to
  30 attempts, waiting 1 second between attempts, and never count as LLM
  calls.
* Failed attempts of the same (model, baseline) combination can simply be
  re-run; run numbering continues automatically.
* Optional llm_config.json next to the BTRun executable may override
  base_url, model, keys and prices.  A "proxy" entry in that file is
  IGNORED: this build always connects directly unless the environment
  variable LLM_PROXY is explicitly set.
* Stop with Ctrl+C; completed repetitions are already on disk.
* If a worker dies mid-run, just re-launch the same command: the numbering
  picks up where it left off.
