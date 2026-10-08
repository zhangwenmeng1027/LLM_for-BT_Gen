# -*- coding: utf-8 -*-
"""
LLM -> BehaVerify BT synthesis experiment with verification feedback (CEGIS loop).

For each benchmark task (Task / description / LTL columns of
Behaverify_benchmark.xlsx):
  1. build a few-shot prompt (prompt_behaverify.txt) + task + its LTLSPECs;
  2. ask the LLM for a complete BehaVerify .tree model;
  3. inject the canonical specifications block (the contract to be verified);
  4. verify with `behaverify nuxmv --generate --do_not_trim --ltl` + NuSMV;
  5. if all specs are true  -> keep the BT (success);
     otherwise             -> retry, up to --max_rounds LLM calls per task.

Baselines (--baseline) control what the LLM is told after a failed attempt:
  full   (default) previous attempt + verifier feedback (failing specs +
                   counterexample trace, or the tool error)   [main method]
  withbt           previous attempt only, no verifier information
  noce             no failure information at all: regenerate from the task

Call-limit / retry policy: --max_rounds (default 5) counts only SUCCESSFUL
LLM calls.  Errors while talking to the API (SSL, timeouts, 5xx, ...) are
retried with exponential backoff (LLM_MAX_ATTEMPTS tries) and never consume
a round; the task only fails if every attempt errors out.

Per-task statistics (in the summary json and the xlsx): success 0/1, LLM call
count, token usage, cost in USD, task wall time, time spent in LLM calls and
time spent in verification.

Results are stored per model, baseline and run as
results/summary_<model>_<N>.json / .xlsx for the full baseline and
results/summary_<model>_<baseline>_<N>.json / .xlsx otherwise (N starts at 1
and increases with every run of the same model+baseline, so --repeat 5 and
repeated invocations stack up as _1, _2, ...).  Candidate trees go to
results/<task>/ (full) or results/<baseline>/<task>/ (baselines).

Usage:
  python llm_bt_gen.py --task ABC3
  python llm_bt_gen.py --tasks ABC3,charge,isFull
  python llm_bt_gen.py --all
  python llm_bt_gen.py --task ABC3 --max_rounds 5 --model gpt-4o
  python llm_bt_gen.py --all --baseline noce --repeat 5 --model gpt-4o
  python llm_bt_gen.py --all --model gpt-4o,gpt-5.5 --repeat 5   # several models

Configuration: llm_config.json (or env vars LLM_BASE_URL / LLM_API_KEY /
LLM_MODEL; optional "prices" object for the cost model).  The verification
toolchain (venv python with behaverify + NuSMV binary) is configured below as
constants.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(HERE, 'prompt_behaverify.txt')
CONFIG_FILE = os.path.join(HERE, 'llm_config.json')
RESULTS_DIR = os.path.join(HERE, 'results')
BENCHMARK_XLSX = os.path.join(HERE, '..', 'behaverify', 'Benchmark', 'Behaverify_benchmark.xlsx')

# ---- verification toolchain -------------------------------------------------
VENV_PY = r'D:\科研\LLM_for_BT_Gen\behaverify_venv\Scripts\python.exe'
NUXMV = r'D:\tools_nusmv\NuSMV-2.7.1-win64\NuSMV-2.7.1-win64\bin\NuSMV.exe'
VERIFY_TIMEOUT = 180          # seconds per behaverify run

# ---- feedback baselines ------------------------------------------------------
# full   = previous BT + verifier feedback (main method)
# withbt = previous BT only, no verifier information
# noce   = no failure information at all (pure re-generation from the task)
BASELINES = ('full', 'noce', 'withbt')

# ---- LLM call retry policy ---------------------------------------------------
# Errors while talking to the API (SSL, timeouts, 5xx, ...) do NOT consume one
# of the task's LLM calls: the call is retried after a fixed wait and only
# successful responses count towards max_rounds.  Both values can be overridden
# per run with --llm_attempts / --llm_retry_wait.
LLM_MAX_ATTEMPTS = 6
LLM_RETRY_WAIT = 5.0          # seconds between attempts (fixed)

# ---- cost model ---------------------------------------------------------------
# USD per 1M tokens, {model prefix: [input, output]}.  Overridden by the
# optional "prices" object in llm_config.json; matched by longest prefix so
# e.g. gpt-4o-mini is not swallowed by gpt-4o.  A model without an entry gets
# cost_usd = None (fix it by adding a "prices" entry for your relay's rates).
DEFAULT_PRICES = {
    'gpt-4o-mini': [0.15, 0.60],
    'gpt-4o': [2.50, 10.00],
    'claude-opus': [5.00, 25.00],
    'claude-sonnet': [3.00, 15.00],
    'claude-haiku': [1.00, 5.00],
    'gemini-2.5-pro': [1.25, 10.00],
    'gemini-2.5-flash': [0.30, 2.50],
}

SPEC_LINE_RE = re.compile(r'-- specification\s+(.+?)\s+is\s+(true|false)', re.IGNORECASE)


# ---------------------------------------------------------------- benchmark IO
def load_benchmark():
    import openpyxl
    wb = openpyxl.load_workbook(BENCHMARK_XLSX)
    ws = wb['benchmark']
    tasks = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        task, desc, ltl = row[0], row[1], row[2]
        if not task:
            continue
        specs = [ln.strip() for ln in str(ltl or '').splitlines() if ln.strip()]
        tasks.append({'task': str(task).strip(), 'description': str(desc or '').strip(),
                      'specs': specs})
    return tasks


# ---------------------------------------------------------------- results xlsx
XLSX_HEADERS = ['Task', 'Success', 'BT', 'LLM Calls', 'Time (s)',
                'LLM Time (s)', 'Verify Time (s)',
                'Prompt Tokens', 'Completion Tokens', 'Total Tokens',
                'Cost (USD)']


def next_summary_paths(model, baseline='full'):
    """Per-run summary paths in RESULTS_DIR: summary_<model>_<N> for the full
    baseline (legacy name), summary_<model>_<baseline>_<N> otherwise.  N is
    the first number not yet taken by that model+baseline, so repeated runs
    (--repeat or re-invocations) stack up as _1, _2, _3 ...  The json and xlsx
    of one run share the same N."""
    stem = 'summary_' + re.sub(r'[^\w.-]', '_', model)
    if baseline != 'full':
        stem += '_' + baseline
    n = 1
    while (os.path.exists(os.path.join(RESULTS_DIR, stem + '_{}.json'.format(n)))
           or os.path.exists(os.path.join(RESULTS_DIR, stem + '_{}.xlsx'.format(n)))):
        n += 1
    base = os.path.join(RESULTS_DIR, '{}_{}'.format(stem, n))
    return base + '.json', base + '.xlsx'


def write_results_xlsx(summary, xlsx_path):
    """Record per-task results in an xlsx: task name, success (0/1), the
    verified BT text (empty when the task was not solved), LLM call count,
    task wall time, LLM call time, verification time, token usage and cost.
    Rows are matched by task name, so separate single-task runs accumulate in
    the same file (old files get the new columns appended)."""
    import openpyxl
    if os.path.exists(xlsx_path):
        wb = openpyxl.load_workbook(xlsx_path)
        ws = wb.active
        for col, h in enumerate(XLSX_HEADERS, start=1):    # extend older header row
            if not ws.cell(row=1, column=col).value:
                ws.cell(row=1, column=col, value=h)
        row_of = {ws.cell(row=r, column=1).value: r
                  for r in range(2, ws.max_row + 1)}
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(XLSX_HEADERS)
        row_of = {}
    for r in summary:
        bt = ''
        if r['success'] and r.get('final_tree') and os.path.exists(r['final_tree']):
            with open(r['final_tree'], encoding='utf-8') as f:
                bt = f.read()
        vals = [r['task'], 1 if r['success'] else 0, bt,
                r.get('n_calls'), r.get('time_s'),
                r.get('llm_time_s'), r.get('verify_time_s'),
                r.get('prompt_tokens'), r.get('completion_tokens'),
                r.get('total_tokens'), r.get('cost_usd')]
        if r['task'] in row_of:
            for col, v in enumerate(vals, start=1):
                ws.cell(row=row_of[r['task']], column=col, value=v)
        else:
            ws.append(vals)
    wb.save(xlsx_path)


# ---------------------------------------------------------------- LLM calling
def load_config():
    cfg = {'base_url': 'https://4sapi.com/v1', 'proxy': 'http://127.0.0.1:6789',
           'model': 'gpt-4o', 'keys': {}}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding='utf-8') as f:
            cfg.update({k: v for k, v in json.load(f).items() if v})
    cfg['model'] = os.environ.get('LLM_MODEL', cfg['model'])
    cfg['proxy'] = os.environ.get('LLM_PROXY', cfg['proxy'])
    cfg['base_url'] = os.environ.get('LLM_BASE_URL', cfg['base_url'])
    select_api_key(cfg)
    return cfg


def select_api_key(cfg):
    """(Re)pick the API key for cfg['model']: explicit env var wins, else the
    first matching model-name prefix from llm_config.json "keys" (as in
    LTLtoBT.py).  Called again whenever a multi-model run switches model."""
    cfg['api_key'] = os.environ.get('LLM_API_KEY', '')
    if not cfg['api_key']:
        for prefix, k in (cfg.get('keys') or {}).items():
            if cfg['model'].startswith(prefix):
                cfg['api_key'] = k
                break


# ---------------------------------------------------------------- cost model
def price_for(cfg, model=None):
    """[input, output] USD per 1M tokens for the model (longest matching
    prefix from llm_config.json "prices" over DEFAULT_PRICES), or None."""
    model = model or cfg['model']
    prices = dict(DEFAULT_PRICES)
    prices.update(cfg.get('prices') or {})
    for prefix in sorted(prices, key=len, reverse=True):
        if model.startswith(prefix):
            return prices[prefix]
    return None


def cost_of(cfg, tokens):
    """Cost in USD of an accumulated token dict, or None if unpriced."""
    price = price_for(cfg)
    if not price:
        return None
    return round(tokens['prompt_tokens'] / 1e6 * price[0]
                 + tokens['completion_tokens'] / 1e6 * price[1], 6)


def call_llm(cfg, prompt):
    """OpenAI-compatible chat call via http.client (mirrors LTLtoBT.py:
    raw Authorization header, optional CONNECT-tunnel through a local proxy)."""
    import http.client
    from urllib.parse import urlparse
    host = urlparse(cfg['base_url']).hostname or '4sapi.com'
    payload = json.dumps({'model': cfg['model'],
                          'messages': [{'role': 'user', 'content': prompt}]})
    headers = {'Accept': 'application/json',
               'Authorization': cfg['api_key'],      # raw key, no Bearer prefix
               'Content-Type': 'application/json'}
    proxy = cfg.get('proxy') or ''
    if proxy:
        p = urlparse(proxy if '//' in proxy else 'http://' + proxy)
        conn = http.client.HTTPSConnection(p.hostname, p.port or 80, timeout=300)
        conn.set_tunnel(host, 443)
    else:
        conn = http.client.HTTPSConnection(host, timeout=300)
    conn.request('POST', '/v1/chat/completions', payload, headers)
    res = conn.getresponse()
    raw = res.read().decode('utf-8', errors='replace')
    if res.status != 200:
        raise RuntimeError('LLM API error {}: {}'.format(res.status, raw[:300]))
    data = json.loads(raw)
    content = data['choices'][0]['message']['content'] or ''
    return content, (data.get('usage') or {})


def call_llm_retry(cfg, prompt, log=print):
    """call_llm with retries for transient errors (SSL, timeouts, 5xx, ...).

    A failed attempt never counts as an LLM call -- the whole point of the
    retry is that only successful responses consume one of max_rounds.  After
    each failure the call is retried after LLM_RETRY_WAIT seconds, up to
    LLM_MAX_ATTEMPTS attempts in total.
    Returns (reply, usage, llm_time_s); llm_time_s accumulates the duration of
    every attempt (failed ones included), sleeps excluded.  Raises the last
    error after LLM_MAX_ATTEMPTS failed attempts."""
    last, llm_time = None, 0.0
    for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
        t0 = time.time()
        try:
            reply, usage = call_llm(cfg, prompt)
            return reply, usage, llm_time + (time.time() - t0)
        except Exception as e:
            llm_time += time.time() - t0
            last = e
            if attempt < LLM_MAX_ATTEMPTS:
                log('  LLM call failed (attempt {}/{}): {} -- retrying in {:.0f}s '
                    '(failed attempts do not count as LLM calls)'.format(
                        attempt, LLM_MAX_ATTEMPTS, e, LLM_RETRY_WAIT))
                time.sleep(LLM_RETRY_WAIT)
    raise last


def mock_llm(prompt, task_name):
    """Offline stand-in: round 1 returns a perturbed tree, round 2 the reference
    tree from the benchmark (demonstrates the feedback-repair loop)."""
    ref = os.path.join(HERE, '..', 'behaverify', 'Benchmark', 'trees', task_name + '.tree')
    if not os.path.exists(ref):
        raise FileNotFoundError('reference tree missing for mock mode: ' + ref)
    with open(ref, encoding='utf-8') as f:
        tree = f.read()
    if 'VERIFIER FEEDBACK' not in prompt:
        i = tree.find(' selector')                      # perturb: selector<->sequence
        if i != -1:
            tree = tree[:i] + ' sequence' + tree[i + len(' selector'):]
    return tree


# ------------------------------------------------------------- tree extraction
def extract_tree(response_text):
    """Pull the .tree content out of the LLM reply (prefer a fenced block)."""
    m = re.search(r'```(?:\w*)\s*\n(.*?)```', response_text, re.DOTALL)
    text = m.group(1) if m else response_text
    start = text.find('configuration')
    if start == -1:
        return None
    return text[start:].strip()


def inject_specs(tree_text, specs):
    """Replace the specifications block with the canonical one from the xlsx."""
    block = 'specifications {\n' + '\n'.join('    ' + s for s in specs) + '\n}'
    m = re.search(r'specifications\s*\{.*?\}\s*$', tree_text, re.DOTALL)
    if m:
        return tree_text[:m.start()] + block + '\n'
    return tree_text.rstrip() + '\n' + block + '\n'


# ---------------------------------------------------------------- verification
def verify_tree(tree_path, out_dir):
    """Run behaverify generation + NuSMV LTL checking.  Returns a report dict."""
    os.makedirs(out_dir, exist_ok=True)
    cmd = [VENV_PY, '-m', 'behaverify', 'nuxmv', tree_path, out_dir,
           '--generate', '--do_not_trim', '--ltl', '--nuxmv_path', NUXMV, '--overwrite']
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=VERIFY_TIMEOUT,
                           env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        rc, so, se = p.returncode, p.stdout or '', p.stderr or ''
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'message': 'verification timed out ({}s)'.format(VERIFY_TIMEOUT),
                'results': [], 'n_true': 0, 'n_false': 0}
    name = os.path.splitext(os.path.basename(tree_path))[0]
    outfile = os.path.join(out_dir, 'nuxmv', name + '_output.txt')
    results = []
    if os.path.exists(outfile):
        with open(outfile, encoding='utf-8', errors='replace') as f:
            content = f.read()
        for m in SPEC_LINE_RE.finditer(content):
            results.append({'spec': m.group(1).strip(), 'result': m.group(2).lower()})
        counterexample = ''
        i = content.find('as demonstrated by')
        if i != -1:
            counterexample = content[i:i + 3000]
    else:
        content = ''
        counterexample = ''
    n_true = sum(1 for r in results if r['result'] == 'true')
    n_false = sum(1 for r in results if r['result'] == 'false')
    if not results:
        # generation or model-checking failed: surface the actual error text
        tail = (se + '\n' + so).strip().splitlines()
        err = '\n'.join(tail[-25:]) or 'no verification output produced'
        return {'status': 'error', 'message': err, 'results': [], 'n_true': 0, 'n_false': 0}
    status = 'pass' if n_false == 0 else 'fail'
    return {'status': status, 'message': '', 'results': results,
            'n_true': n_true, 'n_false': n_false,
            'counterexample': counterexample}


def build_feedback(report, expected_specs):
    """Human/LLM-readable feedback for one failed round."""
    if report['status'] == 'error':
        return ('Your model could not be verified. The tool reported:\n'
                + report['message']
                + '\nFix the model so it is a valid BehaVerify .tree file whose '
                  'tree contains every node referenced by the specifications.')
    lines = []
    for r in report['results']:
        if r['result'] == 'false':
            lines.append('  FALSE: ' + r['spec'])
    fb = ('The verifier found {} violating specification(s) ({} of {} passed):\n'.format(
        len(lines), report['n_true'], len(report['results'])) + '\n'.join(lines))
    if report.get('counterexample'):
        fb += ('\n\nCounterexample trace (excerpt):\n' + report['counterexample'][:2500]
               + '\nThink about WHY the tree lets this trace happen (remember: '
                 'in a sequence, a failing child stops everything; in a selector, '
                 'a child that does NOT fail satisfies it) and produce a '
                 'corrected tree.')
    return fb


# --------------------------------------------------------------- one CEGIS run
def synthesize(cfg, task, max_rounds, baseline='full', log=print):
    """Generate -> verify -> retry loop for one task.

    baseline decides what the LLM sees after a failed attempt:
      full   - previous attempt + verifier feedback (main method)
      withbt - previous attempt only, no verifier information
      noce   - nothing: the plain per-task prompt again (re-generation)

    Collected per-task statistics: success, LLM call count (successful calls
    only), token usage + cost, task wall time, LLM call time and verify time.
    """
    prompt_base = open(PROMPT_FILE, encoding='utf-8').read()
    task_dir = (os.path.join(RESULTS_DIR, task['task']) if baseline == 'full'
                else os.path.join(RESULTS_DIR, baseline, task['task']))
    os.makedirs(task_dir, exist_ok=True)
    history = []          # (round, attempt_text, retry_note) of the last round
    n_calls = 0           # successful LLM calls only
    tokens = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    llm_time = 0.0        # seconds spent inside call_llm (incl. failed attempts)
    verify_time = 0.0     # seconds spent inside verify_tree
    t0 = time.time()

    def done(**res):
        """Stamp task stats (calls / times / tokens / cost) onto a result."""
        res['task'] = task['task']
        res['n_calls'] = n_calls
        res['time_s'] = round(time.time() - t0, 1)
        res['llm_time_s'] = round(llm_time, 1)
        res['verify_time_s'] = round(verify_time, 1)
        res.update(tokens)
        res['cost_usd'] = cost_of(cfg, tokens)
        return res

    for rnd in range(1, max_rounds + 1):
        prompt = prompt_base + '\n\n' + '=' * 70 + '\n'
        prompt += 'TASK: {}\n'.format(task['task'])
        prompt += 'Instruction: {}\n'.format(task['description'])
        prompt += ('The specifications block of your file MUST contain exactly '
                   'these formulas (they will be inserted for you, structure the '
                   'tree so that all of them hold):\n'
                   + '\n'.join(task['specs']) + '\n')
        if history and baseline != 'noce':
            _, prev_attempt, note = history[-1]
            prompt += ('\n\n' + '=' * 70 + '\nYOUR PREVIOUS ATTEMPT:\n' + prev_attempt
                       + '\n\n' + note)
        if not history or baseline == 'noce':
            prompt += ('\nNow output the complete .tree file for the TASK above. '
                       'Output only the file content.')
        log('  round {}: calling LLM...'.format(rnd))
        try:
            if cfg.get('mock'):
                reply, usage, call_s = mock_llm(prompt, task['task']), {}, 0.0
            else:
                reply, usage, call_s = call_llm_retry(cfg, prompt, log)
            n_calls += 1
            llm_time += call_s
            tokens['prompt_tokens'] += usage.get('prompt_tokens') or 0
            tokens['completion_tokens'] += usage.get('completion_tokens') or 0
            tokens['total_tokens'] += usage.get('total_tokens') or (
                (usage.get('prompt_tokens') or 0) + (usage.get('completion_tokens') or 0))
        except Exception as e:
            log('  LLM call still failing after {} attempts: {}'.format(
                LLM_MAX_ATTEMPTS, e))
            return done(success=False, rounds=rnd - 1,
                        reason='LLM error: {}'.format(e), final_tree=None)
        candidate = extract_tree(reply)
        if not candidate:
            note = ('Your previous reply did not contain a .tree model (no '
                    '"configuration" section found). Output only the complete '
                    'file content.')
            history.append((rnd, reply[:2000], note))
            continue
        candidate = inject_specs(candidate, task['specs'])
        cand_path = os.path.join(task_dir, 'round_{}.tree'.format(rnd))
        with open(cand_path, 'w', encoding='utf-8') as f:
            f.write(candidate)
        tv = time.time()
        report = verify_tree(cand_path, os.path.join(task_dir, 'round_{}_out'.format(rnd)))
        verify_time += time.time() - tv
        log('    verify: {} ({} true / {} false)'.format(
            report['status'], report['n_true'], report['n_false']))
        if report['status'] == 'pass':
            final = os.path.join(task_dir, 'final.tree')
            shutil.copy(cand_path, final)
            return done(success=True, rounds=rnd,
                        n_specs=len(report['results']), final_tree=final)
        if baseline == 'full':
            note = ('VERIFIER FEEDBACK:\n' + build_feedback(report, task['specs'])
                    + '\n\nProduce a corrected, complete .tree file.')
        else:
            # withbt / noce: keep the verifier output to ourselves
            note = ('The previous attempt did not satisfy the specifications. '
                    'Produce a corrected, complete .tree file.')
        history.append((rnd, candidate, note))
    return done(success=False, rounds=max_rounds,
                reason='not verified within {} rounds'.format(max_rounds),
                final_tree=None)


# -------------------------------------------------------------------------- cli
def main():
    global RESULTS_DIR, BENCHMARK_XLSX, LLM_MAX_ATTEMPTS, LLM_RETRY_WAIT
    ap = argparse.ArgumentParser()
    ap.add_argument('--task', help='single task name, e.g. ABC3')
    ap.add_argument('--tasks', help='comma separated task names')
    ap.add_argument('--all', action='store_true', help='run the whole benchmark')
    ap.add_argument('--benchmark', default=None,
                    help='task xlsx path (default: the original Behaverify '
                         'benchmark; use complex_tasks.xlsx for the 10-task '
                         'complex benchmark)')
    ap.add_argument('--results_dir', default=None,
                    help='results directory (default: results/; point it at '
                         'results_complex/ for complex-benchmark runs so the '
                         'two experiments do not mix)')
    ap.add_argument('--max_rounds', type=int, default=5,
                    help='LLM call limit per task (default 5; only successful '
                         'calls count, failed API attempts are retried for free)')
    ap.add_argument('--llm_attempts', type=int, default=LLM_MAX_ATTEMPTS,
                    help='max attempts per LLM call before giving up '
                         '(default %(default)s; failed attempts are free)')
    ap.add_argument('--llm_retry_wait', type=float, default=LLM_RETRY_WAIT,
                    help='seconds to wait before retrying a failed LLM call '
                         '(default %(default)s)')
    ap.add_argument('--baseline', choices=BASELINES, default='full',
                    help='full = previous BT + verifier feedback (default); '
                         'withbt = only the previous BT, no verifier info; '
                         'noce = no failure info, regenerate from the task')
    ap.add_argument('--repeat', type=int, default=1,
                    help='run the whole task set N times, one summary per run '
                         '(suffixes _1, _2, ... keep increasing across calls)')
    ap.add_argument('--model', default=None,
                    help='model name, or a comma separated list to run several '
                         'models in one go (e.g. gpt-4o,gpt-5.5): each model '
                         'runs the full task set x --repeat and writes its own '
                         'summaries; API key re-picked per model prefix')
    ap.add_argument('--mock', action='store_true',
                    help='offline mode: canned responses, no API needed (pipeline demo)')
    ap.add_argument('--out', default=None, help='summary json path '
                    '(with --repeat>1 every repeat overwrites this same file)')
    ap.add_argument('--xlsx', default=None,
                    help='results xlsx path (with --repeat>1 rows are re-used)')
    args = ap.parse_args()

    global RESULTS_DIR, BENCHMARK_XLSX
    if args.results_dir:
        RESULTS_DIR = os.path.abspath(args.results_dir)
    if args.benchmark:
        BENCHMARK_XLSX = os.path.abspath(args.benchmark)
    LLM_MAX_ATTEMPTS = args.llm_attempts
    LLM_RETRY_WAIT = args.llm_retry_wait

    cfg = load_config()
    if args.mock:
        cfg['mock'] = True
    models = ([m.strip() for m in args.model.split(',') if m.strip()] if args.model
              else [cfg['model']])

    tasks = load_benchmark()
    if args.task:
        tasks = [t for t in tasks if t['task'] == args.task]
    elif args.tasks:
        want = {s.strip() for s in args.tasks.split(',')}
        tasks = [t for t in tasks if t['task'] in want]
    elif not args.all:
        sys.exit('choose --task NAME, --tasks a,b,c or --all')
    if not tasks:
        sys.exit('no matching task found')

    grand_t0 = time.time()
    for model in models:
        cfg['model'] = model
        select_api_key(cfg)                      # key follows the model prefix
        if not cfg.get('mock') and not cfg['api_key']:
            sys.exit('No API key for model {}: set api_key in llm_config.json '
                     'or env LLM_API_KEY (or use --mock for an offline demo)'.format(model))
        print('\n############ model {} ({}/{}) ############'.format(
            model, models.index(model) + 1, len(models)))
        print('baseline={}  tasks={}  max_rounds={}  repeat={}'.format(
            args.baseline, len(tasks), args.max_rounds, args.repeat))
        if price_for(cfg) is None:
            print('warning: no price configured for {} -- cost_usd will be null; '
                  'add a "prices" entry in llm_config.json'.format(model))

        for rep in range(1, args.repeat + 1):
            if args.repeat > 1:
                print('\n######## repeat {}/{} ########'.format(rep, args.repeat))
            summary = []
            t0 = time.time()
            for t in tasks:
                print('== {} =='.format(t['task']))
                r = synthesize(cfg, t, args.max_rounds, baseline=args.baseline)
                cost = r.get('cost_usd')
                print('   -> {} (rounds={}, calls={}, {:.1f}s | llm {:.1f}s, verify '
                      '{:.1f}s | tokens={} | cost={})'.format(
                          'SUCCESS' if r['success'] else 'FAILED', r['rounds'],
                          r['n_calls'], r['time_s'], r['llm_time_s'],
                          r['verify_time_s'], r['total_tokens'],
                          '${:.4f}'.format(cost) if cost is not None else 'n/a'))
                summary.append(r)
            ok = sum(1 for r in summary if r['success'])
            tot_r = sum(r['rounds'] for r in summary if r['success'])
            print('\n[{}] repeat {}: done in {:.1f}s, {}/{} tasks solved, avg {:.1f} '
                  'rounds for solved ones'.format(
                      model, rep, time.time() - t0, ok, len(summary),
                      (tot_r / ok) if ok else 0.0))
            costs = [r.get('cost_usd') for r in summary]
            cost_txt = ('${:.4f}'.format(sum(c for c in costs if c is not None))
                        + (' (+n/a)' if any(c is None for c in costs) else ''))
            print('LLM calls: {}  |  tokens: {} prompt + {} completion = {} total'.format(
                sum(r['n_calls'] for r in summary),
                sum(r['prompt_tokens'] for r in summary),
                sum(r['completion_tokens'] for r in summary),
                sum(r['total_tokens'] for r in summary)))
            print('LLM time: {:.1f}s  |  verify time: {:.1f}s  |  cost: {}'.format(
                sum(r['llm_time_s'] for r in summary),
                sum(r['verify_time_s'] for r in summary), cost_txt))
            default_json, default_xlsx = next_summary_paths(cfg['model'], args.baseline)
            out = args.out or default_json
            with open(out, 'w', encoding='utf-8') as f:
                json.dump({'model': cfg['model'], 'baseline': args.baseline,
                           'max_rounds': args.max_rounds,
                           'results': summary}, f, ensure_ascii=False, indent=1)
            print('summary written to', out)
            xlsx_out = args.xlsx or default_xlsx
            write_results_xlsx(summary, xlsx_out)
            print('xlsx results written to', xlsx_out)
    print('\nAll done: {} model(s) x {} repeat(s) in {:.1f}s'.format(
        len(models), args.repeat, time.time() - grand_t0))


if __name__ == '__main__':
    main()
