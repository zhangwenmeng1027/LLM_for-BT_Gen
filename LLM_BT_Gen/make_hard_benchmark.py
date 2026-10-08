# -*- coding: utf-8 -*-
"""Build the HARD 70-task benchmark (Behaverify_benchmark_hard.xlsx).

The original benchmark is too easy: its specs only pin SOME of the tree's
transitions (and some are vacuous), so structurally weak trees still verify.
This script keeps the 70 tasks and their reference trees, but REPLACES every
task's specs with a complete, strengthened contract derived from the reference
tree (same generator as the complex benchmark, verified against the runtime
semantics there):
  - an entry spec for the first leaf,
  - a success-chain / failure-fallback spec for EVERY leaf,
  - restart specs pinning every terminal transition (after the root completes
    the BT restarts from the top).

Trees are parsed from ../behaverify/Benchmark/trees/<task>.tree.  Every
strengthened task is verified (reference tree + new specs must pass); tasks
whose tree cannot be parsed or verified keep their ORIGINAL specs so the
benchmark always has all 70 tasks.  The original xlsx is never modified --
run the hard benchmark with llm_bt_gen.py --benchmark ... --results_dir
results_hard so the results stay separate.

Usage:
  python make_hard_benchmark.py               # build xlsx + verify all tasks
  python make_hard_benchmark.py --no-verify   # skip verification (not advised)
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import llm_bt_gen as g
import make_complex_benchmark as mcb          # reuse build_specs / emit helpers

ORIG_XLSX = os.path.join(HERE, '..', 'behaverify', 'Benchmark',
                         'Behaverify_benchmark.xlsx')
TREE_DIR = os.path.join(HERE, '..', 'behaverify', 'Benchmark', 'trees')
HARD_XLSX = os.path.join(HERE, '..', 'behaverify', 'Benchmark',
                         'Behaverify_benchmark_hard.xlsx')
VERIFY_DIR = os.path.join(HERE, 'results_hard_ref')

NAME = r'[A-Za-z_]\w*(?:\(\s*\d+\s*-\s*\d+\s*\))?'      # incl. moveTo(0-0)
TOKEN_RE = re.compile(r'\{|\}|' + NAME)


def strip_comments(text):
    return re.sub(r'#[^\n]*', '', text)


def extract_block(text, keyword):
    """Text between 'keyword {' and its matching close brace ('keyword' must
    start a line, so 'tree' does not match the 'sub_trees' declaration)."""
    m = re.search(r'(?m)^' + keyword + r'\s*\{', text)
    if not m:
        raise ValueError(keyword + ' section not found')
    j = text.find('{', m.start())
    depth, k = 0, j
    while k < len(text):
        if text[k] == '{':
            depth += 1
        elif text[k] == '}':
            depth -= 1
            if depth == 0:
                return text[j + 1:k]
        k += 1
    raise ValueError('unbalanced braces after ' + keyword)


def parse_declared(tree_text):
    """(conditions, actions) declared by the tree file.  Conditions live in
    environment_checks{} (env checks) or checks{} (blackboard checks); either
    way they are leaf nodes that can fail.  A tree may legitimately have no
    conditions (pure action sequence)."""
    txt = strip_comments(tree_text)
    conds = re.findall(r'environment_check\s*\{\s*(' + NAME + ')', txt)
    conds += re.findall(r'(?<!environment_)\bcheck\s*\{\s*(' + NAME + ')', txt)
    acts = re.findall(r'action\s*\{\s*(' + NAME + ')', txt)
    return conds, acts


def tokenize(block):
    return TOKEN_RE.findall(block)


def parse_tree_block(block):
    """Recursive-descent parse of the tree{} body -> nested ('seq'/'sel', [...])."""
    toks = tokenize(block)
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take():
        t = peek()
        pos[0] += 1
        return t

    def parse_node():
        t = take()
        if t != 'composite':
            raise ValueError('expected composite, got ' + repr(t))
        if take() != '{':
            raise ValueError('expected { after composite')
        take()                                    # composite name (c0, ...)
        kind = take()
        if kind not in ('selector', 'sequence'):
            raise ValueError('unsupported composite type ' + repr(kind))
        if take() != 'children' or take() != '{':
            raise ValueError('expected children {')
        children = []
        while True:
            t = peek()
            if t is None:
                raise ValueError('unexpected end of tree block')
            if t == '}':
                take()
                break
            if t == 'composite':
                children.append(parse_node())
            else:                                 # leaf reference
                take()
                if take() != '{' or take() != '}':
                    raise ValueError('malformed leaf ' + repr(t))
                children.append(t)
        if take() != '}':
            raise ValueError('expected } closing composite')
        return ('seq' if kind == 'sequence' else 'sel', children)

    node = parse_node()
    if peek() is not None:
        raise ValueError('trailing tokens in tree block')
    return node


def strengthened(tree_path):
    """New spec lines for a reference tree, or None if not parseable."""
    with open(tree_path, encoding='utf-8') as f:
        text = f.read()
    conds, acts = parse_declared(text)
    if not acts:
        raise ValueError('no actions declared')
    block = extract_block(strip_comments(text), 'tree')
    struct = parse_tree_block(block)
    task = {'task': os.path.splitext(os.path.basename(tree_path))[0],
            'conds': conds, 'acts': acts, 'tree': struct}
    return mcb.build_specs(task)


def verify_with_specs(tree_path, spec_lines, out_dir):
    """Reference tree + injected specs must verify (all true)."""
    with open(tree_path, encoding='utf-8') as f:
        text = f.read()
    injected = g.inject_specs(text, spec_lines)
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, os.path.basename(tree_path))
    with open(p, 'w', encoding='utf-8') as f:
        f.write(injected)
    return g.verify_tree(p, out_dir + '_out'), p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-verify', action='store_true',
                    help='skip verifying the strengthened specs (not advised)')
    args = ap.parse_args()

    import openpyxl
    wb = openpyxl.load_workbook(ORIG_XLSX)
    ws = wb['benchmark']
    tasks = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        orig = [ln.strip() for ln in str(row[2] or '').splitlines() if ln.strip()]
        tasks.append({'task': str(row[0]).strip(), 'desc': str(row[1] or ''),
                      'orig': orig})
    print('{} tasks loaded from {}'.format(len(tasks), os.path.basename(ORIG_XLSX)))

    os.makedirs(VERIFY_DIR, exist_ok=True)
    n_strong, n_kept, failures = 0, 0, []
    for t in tasks:
        tree_path = os.path.join(TREE_DIR, t['task'] + '.tree')
        note = ''
        try:
            if not os.path.exists(tree_path):
                raise FileNotFoundError(tree_path)
            new_specs = strengthened(tree_path)
            if not args.no_verify:
                rep, _ = verify_with_specs(tree_path, new_specs,
                                           os.path.join(VERIFY_DIR, t['task']))
                if rep['status'] != 'pass':
                    raise ValueError('verification failed ({} true / {} false)'
                                     .format(rep['n_true'], rep['n_false']))
            t['specs'] = new_specs
            n_strong += 1
            note = 'strengthened: {} -> {} specs'.format(len(t['orig']),
                                                         len(new_specs))
        except Exception as e:
            t['specs'] = t['orig']             # graceful: keep original specs
            n_kept += 1
            failures.append((t['task'], str(e)[:90]))
            note = 'KEPT ORIGINAL ({} specs): {}'.format(len(t['orig']), e)
        print('  {:22s} {}'.format(t['task'], note))

    wb_out = openpyxl.Workbook()
    ws_out = wb_out.active
    ws_out.title = 'benchmark'
    ws_out.append(['Task', 'Description', 'LTL'])
    for t in tasks:
        ws_out.append([t['task'], t['desc'], '\n'.join(t['specs'])])
    wb_out.save(HARD_XLSX)

    print('\nstrengthened {}/{}, kept original: {} -> {}'.format(
        n_strong, len(tasks), n_kept, HARD_XLSX))
    if failures:
        print('tasks kept at original difficulty:')
        for name, why in failures:
            print('  {:22s} {}'.format(name, why))


if __name__ == '__main__':
    main()
