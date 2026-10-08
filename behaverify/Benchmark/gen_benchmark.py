# -*- coding: utf-8 -*-
"""
Generate the BehaVerify benchmark from the BTLTL benchmark (My_benchmark_ok.xlsx).

Adaptation principles
---------------------
1. Task names and descriptions are kept verbatim (row 69 of the original has an
   empty task name; we name it 'attack2' and flag it).
2. The BTLTL LTL formulas use node-status atoms node_s / node_f / node_r with
   X (next) and G (globally).  BehaVerify has the exact same predicates:
   (success, node), (failure, node), (running, node) plus (next, ...) and
   (globally, ...).  So each formula is translated almost word-for-word.
   Each '&&'-clause becomes one separate LTLSPEC so results are per-formula.
3. Every condition leaf becomes an env BOOLEAN with a nondeterministic initial
   value {True, False} that is frozen afterwards (self-assignment in
   environment_update).  Actions are deterministic and always return success.
   Consequently each tick repeats the same evaluation, which makes the
   next-tick (X) ordering formulas of the benchmark hold exactly when the BT
   structure guarantees the corresponding same-tick ordering.
4. BT structures:  ['?', ...] = selector,  ['>', ...] = sequence.  Several
   original BT strings have unbalanced brackets / stray tokens; they are
   repaired (auto-balanced, or patched explicitly) — see PATCHES.
"""

import json
import re
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP = os.path.join(HERE, '_benchmark_dump.json')
TREE_OUT = os.path.join(HERE, 'trees')

# ----------------------------------------------------------------------------
# Leaf classification: names that are CONDITION (check) nodes; everything else
# is an action node.
# ----------------------------------------------------------------------------
CHECK_NAMES = {
    'atPosA', 'atPosB', 'atPosC', 'atPos3', 'atPos9', 'atPos6', 'atPos2',
    'atKitchen', 'atStation', 'atCharge',
    'alarm', 'empty',
    'isHungry', 'isFull', 'isDay', 'isNight', 'isDoorOpen', 'isInShed',
    'isOnPasture', 'isCharge',
    'lowBattery', 'fullBattery',
    'roomKnown', 'robotInRoom',
    'bottleFound', 'ballFound', 'ballGrasped', 'ballClose', 'boxFound', 'boxNear',
    'invValid', 'equalVal',
    'hasVictim', 'hasFire', 'hasInput', 'hasApple', 'hasData', 'hasSample',
    'holdKnife', 'holdItem', 'holdTools',
    'picked', 'placed', 'placedB', 'ballPlaced',
    'visitedA', 'visitedB', 'visitedC',
    'taskFinishedA', 'taskFinishedB',
    'noFood', 'noCollision', 'noDeliverTask',
    'TargetFound', 'TargetAdjacent', 'TargetCaptured',
    'BatteryOK', 'abilityEvaluated', 'detectionCompleted', 'checkReachable',
    'acceptedMaterial', 'isProcessed', 'RobotAtInvPose',
}

# name normalisation for BehaVerify (avoid reserved-word clashes)
RENAME = {
    'continue': 'continueTask',
    'UseExtinguisher': 'useExtinguisher',
}

# ----------------------------------------------------------------------------
# Patches for known typos / truncations in the original benchmark strings
# (each patch is justified by the task's own description and LTL formulas)
# ----------------------------------------------------------------------------
BT_PATCHES = {
    # stray '>' atom outside a list
    'openDoor': "['?', 'isDoorOpen', ['>', 'openDoor', 'passThroughDoor']]",
    # two top-level lists; description says "chooses to perform ... two branch tasks" -> selector root
    'acceptDoOtherTask': ("['?', ['>', 'lowBattery', 'closeGripper', 'goToStation', 'charging'], "
                          "['>', ['>', 'goToPosA', 'doTaskA', 'goToPosB', 'doTaskB', 'goToPosC', 'doTaskC'], "
                          "['?', 'hasInput', 'waitInput'], ['?', 'invValid', 'computInv'], "
                          "['>', 'searchTarget', 'activeManipulator']]"),
    # description: "... put down the item, and finally MOVE IT TO THE PARKING LOT" (node missing from BT string)
    'evaluate': ("['>', ['?', 'abilityEvaluated', ['>', 'testPerformance', 'evaluationPerformance']], "
                 "['>', 'pickUp', 'moveToDestination', 'putDown', 'moveToParking']]"),
    # description Task 2: "Seek help" (askHelp missing, string truncated)
    'hungry_kitchen': ("['?', ['>', 'isHungry', ['?', 'goToKitchen', 'followHuman'], ['>', 'locateBottle', 'fetchBottle']], "
                       "'askHelp']"),
    # description Task 2: "Seek help" (askHelp missing, string truncated)
    'pour_drink': ("['?', ['>', ['?', ['>', 'roomKnown', 'goToRoom'], 'followHuman'], "
                   "['>', 'findBottle', 'fetchBottle', 'findGlass', 'fetchGlass', 'pourDrink']], 'askHelp']"),
    # description: "move to position B ..." (original BT wrote goToPosA twice and dropped eatfood)
    'attackTarget': ("['?', ['>', 'getTarget', 'goToPosA', ['?', 'TargetAdjacent', 'attackTarget']], "
                     "['?', ['>', 'isHungry', 'findFood', 'goToPosB', 'findTableware', 'eatfood'], 'followHuman']]"),
    # row 69 (empty task name) - attack/randomMove variant
    '': "['?', ['>', 'getTarget', 'moveToDestination', 'TargetAdjacent', 'attackTarget'], 'randomMove']",
}

LTL_PATCHES = {
    # original: G(invValid_f) -> X(pushP_s ...)   (paren typo in source)
    'roomKnown': ("G(invValid_f -> X(pushP_s || pushP_f || pushP_r)) && G(pushP_s -> X(goToStation_s || goToStation_f || goToStation_r)) "
                  "&& G(goToStation_s -> X(sleeping_s || sleeping_f || sleeping_r))"),
    # original ends with ... doTaskB_r)))]  (extra closing paren before ])
    'alarm5': ("G(alarm_s -> X(taskFinishedA_s || taskFinishedA_f)) &&  G(taskFinishedA_f -> X(atPosA_s || atPosA_f)) , "
               "G(atPosA_s -> X(doTaskA_s || doTaskA_f || doTaskA_r)) && G(goToPosA_s -> X(doTaskA_s || doTaskA_f || doTaskA_r)) , "
               "G(alarm_f -> X(taskFinishedB_s || taskFinishedB_f)) &&  G(taskFinishedB_f -> X(atPosB_s || atPosB_f)) , "
               "G(atPosB_s -> X(doTaskB_s || doTaskB_f || doTaskB_r)) && G(goToPosB_s -> X(doTaskB_s || doTaskB_f || doTaskB_r))"),
}

TASKNAME_OVERRIDE = {'': 'attack2'}   # original row 69 had an empty task name


# ----------------------------------------------------------------------------
# BT string parsing
# ----------------------------------------------------------------------------
def tokenize_bt(s):
    s = re.sub(r"[\'\"]", ' ', s)              # drop quotes first
    s = s.replace('?', ' ? ').replace('>', ' > ')
    s = s.replace('[', ' [ ').replace(']', ' ] ').replace(',', ' , ')
    toks = [t for t in s.split() if t]
    # merge '[' + '?' / '>' into composite markers
    merged, i = [], 0
    while i < len(toks):
        if toks[i] == '[' and i + 1 < len(toks) and toks[i + 1] in ('?', '>'):
            merged.append('[?' if toks[i + 1] == '?' else '[>')
            i += 2
        else:
            merged.append(toks[i])
            i += 1
    return merged


def parse_list(tokens, pos):
    """tokens[pos] is '[?'/'[>'; returns (kind, children, new pos)."""
    marker = tokens[pos]           # '[?' selector / '[>' sequence
    kind = 'sel' if marker == '[?' else 'seq'
    pos += 1
    children = []
    while pos < len(tokens):
        t = tokens[pos]
        if t == ']':
            return (kind, children, pos + 1)
        if t == ',':
            pos += 1
            continue
        if t in ('[?', '[>'):
            kind2, kids, pos = parse_list(tokens, pos)
            children.append((kind2, kids))
        elif t in ('?', '>'):
            pos += 1                               # stray marker token — skip
        else:
            children.append(('leaf', t))
            pos += 1
    return (kind, children, pos)   # unbalanced: auto-close


def parse_bt(bt_str):
    toks = tokenize_bt(bt_str)
    while toks and toks[0] not in ('[?', '[>'):
        toks = toks[1:]
    if not toks:
        raise ValueError('no composite found')
    kind, children, pos = parse_list(toks, 0)
    return (kind, children)        # trailing leftovers ignored


# ----------------------------------------------------------------------------
# LTL string parsing: atoms node_s/node_f/node_r, X(...), G(...), &&, ||, ->
# ----------------------------------------------------------------------------
ATOM = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)_(s|f|r)\b')


def split_top(s, sep):
    """split s on (possibly multi-char) sep at bracket depth 0"""
    parts, depth, cur, i, n = [], 0, '', 0, len(s)
    while i < n:
        ch = s[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if depth == 0 and s.startswith(sep, i):
            parts.append(cur)
            cur = ''
            i += len(sep)
            continue
        cur += ch
        i += 1
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def translate_formula(f, instances=None):
    """Translate one infix LTL formula (no top-level &&) into BehaVerify prefix.

    instances: orig node name -> list of instance names in the tree.  When a
    logical node is cloned (BehaVerify needs unique node names), an atom over
    the node becomes the disjunction over all its instances.
    """
    f = f.strip()
    # implication  a -> b   (lowest precedence)
    parts = split_top(f, '->')
    if len(parts) >= 2:
        left = ' && '.join(parts[:-1])          # a1 -> a2 -> b  ==  (a1&&a2)->b
        return '(implies, {}, {})'.format(translate_formula(left, instances), translate_formula(parts[-1], instances))
    parts = split_top(f, '&&')
    if len(parts) > 1:
        return '(' + ', '.join(['and'] + [translate_formula(p, instances) for p in parts]) + ')'
    parts = split_top(f, '||')
    if len(parts) > 1:
        return '(' + ', '.join(['or'] + [translate_formula(p, instances) for p in parts]) + ')'
    # unary
    m = re.match(r'^X\s*\((.*)\)$', f)
    if m:
        return '(next, {})'.format(translate_formula(m.group(1), instances))
    m = re.match(r'^G\s*\((.*)\)$', f)
    if m:
        return '(globally, {})'.format(translate_formula(m.group(1), instances))
    m = re.match(r'^F\s*\((.*)\)$', f)
    if m:
        return '(finally, {})'.format(translate_formula(m.group(1), instances))
    # atom or parenthesised subformula
    if f.startswith('(') and f.endswith(')'):
        return translate_formula(f[1:-1], instances)
    m = ATOM.fullmatch(f)
    if m:
        name, suf = m.group(1), m.group(2)
        name = RENAME.get(name, name)
        pred = {'s': 'success', 'f': 'failure', 'r': 'running'}[suf]
        insts = (instances or {}).get(name, [name])
        if len(insts) == 1:
            return '({}, {})'.format(pred, insts[0])
        return '(' + ', '.join(['or'] + ['({}, {})'.format(pred, i) for i in insts]) + ')'
    if f in ('True', 'true'):
        return 'True'
    if f in ('False', 'false'):
        return 'False'
    raise ValueError('cannot translate atom: ' + repr(f))


def translate_ltl(ltl_str, instances=None):
    """Benchmark LTL cell -> list of BehaVerify LTLSPEC bodies (one per clause)."""
    s = ltl_str.strip().strip('[]')
    clauses = []
    for chunk in split_top(s, ','):
        for part in split_top(chunk, '&&'):
            clauses.append(part.strip())
    specs = []
    for c in clauses:
        c = re.sub(r'\s+', ' ', c).strip()
        if not c:
            continue
        specs.append(translate_formula(c, instances))
    return specs


# ----------------------------------------------------------------------------
# Tree normalisation: splice single-child composites, clone repeated leaves
# ----------------------------------------------------------------------------
def splice_single_child(node):
    """BehaVerify composites need >= 2 children: hoist only-children upwards."""
    kind, children = node
    new_children = []
    for ch in children:
        if ch[0] == 'leaf':
            new_children.append(ch)
        else:
            spliced = splice_single_child(ch)
            if len(spliced[1]) == 1:
                new_children.extend(spliced[1])
            else:
                new_children.append(spliced)
    if not new_children:
        raise ValueError('composite lost all children')
    if len(new_children) == 1 and new_children[0][0] == 'composite_passthrough':
        pass
    return (kind, new_children)


def clone_leaves(node, counter=None, instances=None):
    """Assign unique instance names to leaves (foo, foo_2, foo_3, ...)."""
    if counter is None:
        counter = {}
    if instances is None:
        instances = {}
    kind, children = node
    new_children = []
    for ch in children:
        if ch[0] == 'leaf':
            orig = RENAME.get(ch[1], ch[1])
            counter[orig] = counter.get(orig, 0) + 1
            inst = orig if counter[orig] == 1 else '{}_{}'.format(orig, counter[orig])
            instances.setdefault(orig, []).append(inst)
            new_children.append(('leaf', inst))
        else:
            new_children.append(clone_leaves(ch, counter, instances))
    return (kind, new_children)


# ----------------------------------------------------------------------------
# .tree emission
# ----------------------------------------------------------------------------
def collect_leaves(node, acc):
    kind, children = node[0], node[1]
    if kind == 'leaf':
        acc.append(node[1])
    else:
        for ch in children:
            collect_leaves(ch, acc)


def bt_to_dsl(node, counter):
    """nested (kind, children) -> DSL text; returns (text, name)"""
    kind, children = node[0], node[1]
    name = 'c{}'.format(next(counter))
    lines = ['composite {', '    {} {}'.format(name, 'selector' if kind == 'sel' else 'sequence'), '    children {']
    for ch in children:
        if ch[0] == 'leaf':
            leaf = RENAME.get(ch[1], ch[1])
            lines.append('        {} {{}}'.format(leaf))
        else:
            sub, _ = bt_to_dsl(ch, counter)
            for ln in sub.splitlines():
                lines.append('    ' + ln)
    lines.append('    }')
    lines.append('}')
    return '\n'.join(lines), name


def bt_to_pretty(node):
    """nested list notation in BehaVerify style for the xlsx BT column"""
    kind, children = node[0], node[1]
    kw = 'selector' if kind == 'sel' else 'sequence'
    parts = []
    for ch in children:
        if ch[0] == 'leaf':
            parts.append(RENAME.get(ch[1], ch[1]))
        else:
            parts.append(bt_to_pretty(ch))
    return kw + '(' + ', '.join(parts) + ')'


def base_name(inst):
    """instance name foo_2 -> logical name foo (undo clone suffix)"""
    m = re.match(r'^(.*)_(\d+)$', inst)
    if m and m.group(2) != '1':
        return m.group(1)
    return inst


def gen_tree(task, bt_node, specs):
    leaves = []
    collect_leaves(bt_node, leaves)
    seen, ordered = set(), []
    for lf in leaves:                       # instance names (already unique)
        if lf not in seen:
            seen.add(lf)
            ordered.append(lf)
    checks = [n for n in ordered if base_name(n) in CHECK_NAMES]
    actions = [n for n in ordered if n not in checks]

    out = []
    out.append('configuration {} enumerations {} constants {}')
    out.append('variables {')
    for c in checks:
        out.append('    variable {{ env {}_v VAR BOOLEAN assign{{result{{True, False}}}} }}'.format(c))
    out.append('}')
    out.append('environment_update {')
    for c in checks:
        out.append('    variable_statement{{ {}_v assign{{result{{{}_v}}}} }}'.format(c, c))
    out.append('}')
    out.append('checks {}')
    out.append('environment_checks {')
    for c in checks:
        out.append('    environment_check {{ {} arguments {{}} read_variables {{{}_v}} condition{{{}_v}} }}'.format(c, c, c))
    out.append('}')
    out.append('actions {')
    for a in actions:
        out.append('    action {{ {}'.format(a))
        out.append('        arguments {} local_variables{} read_variables{} write_variables{} initial_values{}')
        out.append('        update { return_statement{result{success}} }')
        out.append('    }')
    out.append('}')
    out.append('sub_trees {}')
    counter = iter(range(1000))
    body, _ = bt_to_dsl(bt_node, counter)
    out.append('tree {')
    for ln in body.splitlines():
        out.append('    ' + ln)
    out.append('}')
    out.append('tick_prerequisite {True}')
    out.append('specifications {')
    for sp in specs:
        out.append('    LTLSPEC {{{}}}'.format(sp))
    out.append('}')
    return '\n'.join(out) + '\n'


# ----------------------------------------------------------------------------
def main():
    with open(DUMP, encoding='utf-8') as f:
        rows = json.load(f)
    os.makedirs(TREE_OUT, exist_ok=True)
    results = []
    for row in rows:
        orig_name = row['task']
        task = TASKNAME_OVERRIDE.get(orig_name, orig_name) or TASKNAME_OVERRIDE['']
        bt_str = row['bt'].strip()
        if orig_name in BT_PATCHES:
            bt_str = BT_PATCHES[orig_name]
        ltl_str = row['ltl'].strip()
        if orig_name in LTL_PATCHES:
            ltl_str = LTL_PATCHES[orig_name]
        try:
            bt_node = parse_bt(bt_str)
            bt_node = splice_single_child(bt_node)
            instances = {}
            bt_node = clone_leaves(bt_node, None, instances)
            # validate: every node referenced by a spec atom must exist
            for orig, insts in instances.items():
                pass
            missing = []
            for m in ATOM.finditer(re.sub(r'\s+', ' ', ltl_str)):
                nm = RENAME.get(m.group(1), m.group(1))
                if nm not in instances:
                    missing.append(nm)
            if missing:
                raise ValueError('spec references nodes not in BT: ' + ', '.join(sorted(set(missing))))
            specs = translate_ltl(ltl_str, instances)
            tree_text = gen_tree(task, bt_node, specs)
            fname = task + '.tree'
            with open(os.path.join(TREE_OUT, fname), 'w', encoding='utf-8') as f:
                f.write(tree_text)
            results.append({
                'task': task,
                'orig_task': orig_name,
                'description': row['description'],
                'specs': specs,
                'bt_pretty': bt_to_pretty(bt_node),
                'tree_file': 'trees/' + fname,
                'status': 'ok',
            })
        except Exception as e:
            results.append({
                'task': task, 'orig_task': orig_name,
                'description': row['description'],
                'specs': [], 'bt_pretty': '', 'tree_file': '',
                'status': 'ERROR: {}'.format(e),
            })
    with open(os.path.join(HERE, '_benchmark_new.json'), 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    bad = [r for r in results if r['status'] != 'ok']
    print('generated {} tasks, {} errors'.format(len(results), len(bad)))
    for b in bad:
        print(' !!', b['orig_task'], '->', b['status'])


if __name__ == '__main__':
    main()
