# -*- coding: utf-8 -*-
"""Build the COMPLEX benchmark: 10 hard tasks (BehaVerify_benchmark_complex.xlsx)
plus a verified reference .tree for every task.

Why a generator: the benchmark's LTLSPECs pin down the tree's tick-by-tick
dynamics ("when node X returns S, next tick node(s) Y return ..."), so specs
and tree must match EXACTLY or the task is unsolvable.  This script derives
the spec lines AUTOMATICALLY from the reference tree structure (same style as
the original benchmark: an entry spec for the first leaf, success-chains
along sequences, failure-fallbacks along selectors, nothing after the root
completes), then verifies every reference tree with the real toolchain --
only tasks whose reference tree passes (all specs true) are kept, so every
published task is solvable.

Tree structure is written as nested python lists:
    ('seq', [child, ...]) / ('sel', [child, ...]) / 'NodeName'
where NodeName in conds = condition (environment_check, may fail),
      NodeName in acts = action (always returns success).

Usage:
  python make_complex_benchmark.py                 # build xlsx + trees + verify
  python make_complex_benchmark.py --no-verify     # skip the verification step
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import llm_bt_gen as g                          # reuse VENV_PY / verify_tree

XLSX_OUT = os.path.join(HERE, 'complex_tasks.xlsx')
TREE_DIR = os.path.join(HERE, '..', 'behaverify', 'Benchmark', 'trees')
VERIFY_DIR = os.path.join(HERE, 'results_complex_ref')

HEADER = ['Task', 'Description', 'LTL']


# ------------------------------------------------------------- DSL emission
def leaves(node, conds, acts):
    if isinstance(node, str):
        return [node]
    out = []
    for ch in node[1]:
        out.extend(leaves(ch, conds, acts))
    return out


def first_leaf(node, conds, acts):
    return leaves(node, conds, acts)[0]


def check_names(task):
    conds, acts = set(task['conds']), set(task['acts'])
    used = leaves(task['tree'], conds, acts)
    dup = sorted({n for n in used if used.count(n) > 1})
    if dup:
        raise ValueError('{}: duplicate node(s) {}'.format(task['task'], dup))
    unk = [n for n in used if n not in conds and n not in acts]
    if unk:
        raise ValueError('{}: undeclared node(s) {}'.format(task['task'], unk))
    return conds, acts


def emit_tree(node, conds, acts, counter):
    """Emit BehaVerify DSL for the tree body; returns (text, first_leaf)."""
    if isinstance(node, str):
        return '            {} {{}}\n'.format(node), node
    kind, children = node
    name = 'c{}'.format(counter[0])
    counter[0] += 1
    kind_txt = {'seq': 'sequence', 'sel': 'selector'}[kind]
    body = '    composite {{\n        {} {}\n        children {{\n'.format(name, kind_txt)
    firsts = []
    for ch in children:
        txt, fl = emit_tree(ch, conds, acts, counter)
        body += txt
        firsts.append(fl)
    body += '        }\n    }\n'
    return body, firsts[0]


def _status_or(name, conds):
    """Disjunction over the possible outcomes of `name` next tick."""
    if name in conds:
        return '(or, (success, {0}), (failure, {0}))'.format(name)
    return '(or, (success, {0}), (failure, {0}), (running, {0}))'.format(name)


def build_specs(task):
    """Derive the LTL lines from the tree: entry spec, success-chains,
    failure-fallbacks and restart specs (after the root completes the BT
    restarts from the top, so every terminal transition is pinned too)."""
    conds, acts = check_names(task)
    root = task['tree']
    specs = []
    succ_of, fail_of = {}, {}                  # leaf -> next leaf reached

    def walk(node, on_succ, on_fail):
        """on_succ/on_fail = leaf reached next when `node` succeeds/fails."""
        if isinstance(node, str):
            succ_of[node] = on_succ
            fail_of[node] = on_fail
            return node
        kind, children = node
        for i, ch in enumerate(children):
            ch_first = first_leaf(ch, conds, acts)
            if kind == 'seq':
                nxt = (first_leaf(children[i + 1], conds, acts)
                       if i + 1 < len(children) else on_succ)
                walk(ch, nxt, on_fail)
            else:                              # selector
                nxt_fail = (first_leaf(children[i + 1], conds, acts)
                            if i + 1 < len(children) else on_fail)
                walk(ch, on_succ, nxt_fail)
        return first_leaf(node, conds, acts)

    walk(root, None, None)
    entry = first_leaf(root, conds, acts)
    restart = '(or, (success, {0}), (failure, {0}))'.format(entry)
    specs.append('LTLSPEC {{(next, (or, (success, {0}), (failure, {0})))}}'.format(entry))
    for leaf in leaves(root, conds, acts):
        for status, nxt in (('success', succ_of[leaf]), ('failure', fail_of[leaf])):
            if leaf in acts and status == 'failure':
                continue                       # actions never fail
            if nxt is None:                    # root completion -> BT restarts
                specs.append('LTLSPEC {{(globally, (implies, ({}, {}), '
                             '(next, {})))}}'.format(status, leaf, restart))
                continue
            specs.append('LTLSPEC {{(globally, (implies, ({}, {}), (next, {})))}}'
                         .format(status, leaf, _status_or(nxt, conds)))
    return specs


def emit_file(task):
    """Write the complete reference .tree (declares + tree + specifications)."""
    conds, acts = check_names(task)
    body, _ = emit_tree(task['tree'], conds, acts, counter=[0])

    variables = ''.join(
        '    variable {{ env {}_v VAR BOOLEAN assign{{result{{True, False}}}} }}\n'
        .format(c) for c in task['conds'])
    env_upd = ''.join(
        '    variable_statement{{ {}_v assign{{result{{{}_v}}}} }}\n'.format(c, c)
        for c in task['conds'])
    checks = ''.join(
        '    environment_check {{ {} arguments {{}} read_variables {{{}_v}} '
        'condition{{{}_v}} }}\n'.format(c, c, c) for c in task['conds'])
    action_txt = ''.join(
        '    action {{ {}\n        arguments {{}} local_variables{{}} '
        'read_variables{{}} write_variables{{}} initial_values{{}}\n'
        '        update {{ return_statement{{result{{success}}}} }}\n    }}\n'
        .format(a) for a in task['acts'])
    spec_txt = ''.join('    {}\n'.format(s) for s in task['specs'])

    return ('configuration {{}} enumerations {{}} constants {{}}\n'
            'variables {{\n{v}}}\n'
            'environment_update {{\n{u}}}\n'
            'checks {{}}\n'
            'environment_checks {{\n{c}}}\n'
            'actions {{\n{a}}}\n'
            'sub_trees {{}}\n'
            'tree {{\n{t}}}\n'
            'tick_prerequisite {{True}}\n'
            'specifications {{\n{s}}}\n').format(v=variables, u=env_upd, c=checks,
                                                 a=action_txt, t=body, s=spec_txt)


# ------------------------------------------------------- the 10 hard tasks
def seq(*children):
    return ('seq', list(children))


def sel(*children):
    return ('sel', list(children))


TASKS = [
    dict(task='CX1_deep_delivery',
         conds=['isDay', 'isDoorOpen', 'checkReachable', 'picked'],
         acts=['openDoor', 'askHelp', 'goToPosA', 'pickUp', 'pickUp_2',
               'goToPosB', 'placeB', 'closeGripper'],
         tree=seq('isDay',
                  sel('isDoorOpen', 'openDoor'),
                  sel('checkReachable', 'askHelp'),
                  'goToPosA',
                  sel('picked', 'pickUp_2'),
                  'goToPosB',
                  'placeB',
                  'closeGripper'),
         desc=('Execute the following delivery procedure strictly in sequence, '
               'checking every precondition before acting and recovering from '
               'failures as specified.\n\n'
               'Task 1: Verify that it is daytime; only proceed during the day.\n'
               'Task 2: Check whether the door is open; if the door is closed, '
               'open the door first.\nTask 3: Check whether the path is '
               'reachable; if it is NOT reachable, ask a human for help first.\n'
               'Task 4: Navigate to position A.\nTask 5: Pick up the object at '
               'position A; if the object was not picked up afterwards, retry '
               'by picking it up once more.\nTask 6: Navigate to position B.\n'
               'Task 7: Place the object at position B.\n'
               'Task 8: Close the gripper to finish the delivery.')),

    dict(task='CX2_hazard_dispatch',
         conds=['hasFire', 'TargetAdjacent', 'hasVictim', 'checkReachable',
                'alarm', 'atStation', 'lowBattery', 'atCharge', 'isHungry',
                'empty'],
         acts=['goToPosA', 'useExtinguisher', 'askHelp', 'goToPosC',
               'saveVictim', 'goToStation', 'closeDoor', 'goToStation_2',
               'charging', 'findFood', 'eatfood', 'goToPosB', 'doTaskA'],
         tree=sel(seq('hasFire', sel('TargetAdjacent', 'goToPosA'),
                      'useExtinguisher'),
                  seq('hasVictim', sel('checkReachable', 'askHelp'),
                      'goToPosC', 'saveVictim'),
                  seq('alarm', sel('atStation', 'goToStation'), 'closeDoor'),
                  seq('lowBattery', sel('atCharge', 'goToStation_2'),
                      'charging'),
                  seq('isHungry', 'findFood', 'eatfood'),
                  seq('empty', 'goToPosB', 'doTaskA')),
         desc=('Choose exactly one branch to execute according to the following '
               'priority order (try the highest priority first; if its leading '
               'condition does not hold, move on to the next branch).\n\n'
               'Branch 1 (highest priority): If there is a fire source, first '
               'make sure the target is nearby (navigate to position A if it is '
               'not), then use the fire extinguisher.\n'
               'Branch 2: If a victim is present, check whether the path is '
               'reachable (if not, ask a human for help first), navigate to '
               'position C and rescue the victim.\n'
               'Branch 3: If the alarm is sounding, go to the base station '
               '(navigate only if not already there) and close the door.\n'
               'Branch 4: If the battery is low, go to the charging station '
               '(navigate only if not already there) and charge the robot.\n'
               'Branch 5: If the robot is hungry, search for food and eat the '
               'food.\nBranch 6 (lowest priority): If the hands are empty, '
               'navigate to position B and execute task A.')),

    dict(task='CX3_battery_guard',
         conds=['fullBattery', 'lowBattery', 'atCharge', 'isCharge'],
         acts=['goToPosA', 'doTaskA', 'goToPosB', 'doTaskB', 'goToPosC',
               'doTaskC', 'goToStation', 'charging', 'stopCharge',
               'goToPosB_2', 'doTaskB_2'],
         tree=sel(seq('fullBattery', 'goToPosA', 'doTaskA', 'goToPosB',
                      'doTaskB', 'goToPosC', 'doTaskC'),
                  seq('lowBattery', sel('atCharge', 'goToStation'), 'charging'),
                  seq('isCharge', 'stopCharge', 'goToPosB_2', 'doTaskB_2')),
         desc=('Manage the battery state machine and the work queue.\n\n'
               'Branch 1: If the battery is fully charged, execute the full '
               'work queue in order: navigate to position A and execute task A, '
               'then navigate to position B and execute task B, then navigate '
               'to position C and execute task C.\n'
               'Branch 2: If the battery level is low, go to the charging '
               'station (if the robot is already at the charging station, skip '
               'navigation) and charge the robot.\n'
               'Branch 3: If the robot is currently charging, stop charging, '
               'then navigate to position B and execute task B.')),

    dict(task='CX4_day_night_patrol',
         conds=['isDay', 'visitedA', 'visitedB', 'visitedC', 'isNight',
                'atStation', 'fullBattery', 'isDoorOpen'],
         acts=['unfoldPanels', 'goToPosA', 'patroling', 'goToPosB',
               'patroling_2', 'goToPosC', 'patroling_3', 'goToStation',
               'charging', 'foldPanels', 'closeDoor'],
         tree=sel(seq('isDay', 'unfoldPanels',
                      sel('visitedA', seq('goToPosA', 'patroling')),
                      sel('visitedB', seq('goToPosB', 'patroling_2')),
                      sel('visitedC', seq('goToPosC', 'patroling_3'))),
                  seq('isNight', sel('atStation', 'goToStation'), 'charging',
                      sel('fullBattery', 'foldPanels'),
                      sel('isDoorOpen', 'closeDoor'))),
         desc=('The robot behaves differently at day and at night.\n\n'
               'Day mode (if it is daytime): deploy the solar panels, then '
               'patrol three locations in order. For each location: if it has '
               'already been visited, skip it; otherwise navigate there and '
               'patrol.\n- Location A: navigate to position A and patrol.\n'
               '- Location B: navigate to position B and patrol.\n'
               '- Location C: navigate to position C and patrol.\n'
               'Night mode (if it is night): go to the base station (navigate '
               'only if not already there), charge the robot; once the battery '
               'is fully charged, retract the solar panels; finally, if the '
               'door is open, close the door.')),

    dict(task='CX5_rescue_recovery',
         conds=['hasVictim', 'checkReachable', 'placed', 'hasData'],
         acts=['askHelp', 'goToPosC', 'saveVictim', 'putDown', 'send'],
         tree=seq('hasVictim',
                  sel('checkReachable', 'askHelp'),
                  'goToPosC',
                  'saveVictim',
                  sel('placed', 'putDown'),
                  sel('hasData', 'send')),
         desc=('Execute the multi-stage rescue procedure strictly in sequence '
               'with recovery and reporting steps.\n\n'
               'Task 1: Check whether a victim is present.\nTask 2: Check '
               'whether the path to the victim is reachable; if it is NOT '
               'reachable, ask a human for help first.\nTask 3: Navigate to '
               'position C.\nTask 4: Rescue the victim.\nTask 5: Check whether '
               'the victim has been placed safely; if not, put down the held '
               'object.\nTask 6: Check whether mission data is available; if '
               'yes, send the report.')),

    dict(task='CX6_bottle_multiloc',
         conds=['bottleFound', 'holdItem', 'bottleFound_2', 'TargetAdjacent',
                'bottleFound_3', 'TargetAdjacent_2', 'bottleFound_4'],
         acts=['fetchBottle', 'goToPosB', 'goToPosB_2', 'goToPosC',
               'goToPosC_2', 'goToPos3', 'goToKitchen'],
         tree=sel(seq('bottleFound', sel('holdItem', 'fetchBottle')),
                  seq('bottleFound_2', 'goToPosB',
                      sel('TargetAdjacent', 'goToPosB_2')),
                  seq('bottleFound_3', 'goToPosC',
                      sel('TargetAdjacent_2', 'goToPosC_2')),
                  seq('bottleFound_4', 'goToPos3'),
                  'goToKitchen'),
         desc=('Search for a bottle in four candidate locations and fall back '
               'to a default behaviour.\n\nBranch 1: If a bottle has been found '
               'at the current location, make sure it is being held (retrieve '
               'the bottle if not).\nBranch 2: If a bottle has been found near '
               'position B, navigate to position B; if afterwards the target is '
               'not adjacent, navigate to position B once more.\nBranch 3: If a '
               'bottle has been found near position C, navigate to position C; '
               'if afterwards the target is not adjacent, navigate to position '
               'C once more.\nBranch 4: If a bottle has been found near '
               'position 3, navigate to position 3.\nBranch 5 (default): If no '
               'bottle has been found anywhere, navigate to the kitchen and '
               'keep searching there.')),

    dict(task='CX7_kitchen_cycle',
         conds=['isHungry', 'hasApple', 'noFood', 'hasApple_2', 'isFull',
                'empty', 'isNight'],
         acts=['pickApple', 'eatfood', 'findFood', 'pickApple_2', 'eatfood_2',
               'putDown', 'goToStation', 'goToKitchen'],
         tree=sel(seq('isHungry', sel('hasApple', 'pickApple'), 'eatfood'),
                  seq('noFood', 'findFood',
                      sel('hasApple_2', 'pickApple_2'), 'eatfood_2'),
                  seq('isFull', sel('empty', 'putDown'), 'goToStation'),
                  seq('isNight', 'goToKitchen')),
         desc=('Manage food-related and end-of-day behaviours by priority.\n\n'
               'Branch 1: If the robot is hungry, eat: first check whether an '
               'apple tree is nearby, and if yes pick the apple before eating '
               'the food.\nBranch 2: If no food is available, search for food; '
               'then if an apple tree is nearby pick the apple, and finally eat '
               'the food.\nBranch 3: If the robot is full, check whether the '
               'hands are empty; if they are NOT empty, put down the held '
               'object first, then navigate to the base station.\n'
               'Branch 4: If it is night, navigate to the kitchen.')),

    dict(task='CX8_guard_shift',
         conds=['alarm', 'hasFire', 'atStation', 'hasVictim', 'isDay',
                'visitedA', 'visitedB', 'isNight', 'atStation_2'],
         acts=['useExtinguisher', 'goToStation', 'closeDoor', 'askHelp',
               'goToPosA', 'patroling', 'goToPosB', 'patroling_2',
               'goToStation_2', 'charging'],
         tree=sel(seq('alarm', sel('hasFire', 'useExtinguisher'),
                      sel('atStation', 'goToStation'), 'closeDoor'),
                  seq('hasVictim', 'askHelp'),
                  seq('isDay',
                      sel('visitedA', seq('goToPosA', 'patroling')),
                      sel('visitedB', seq('goToPosB', 'patroling_2'))),
                  seq('isNight', sel('atStation_2', 'goToStation_2'),
                      'charging')),
         desc=('A security guard robot with layered emergency overrides.\n\n'
               'Branch 1 (highest priority, alarm): If the alarm is sounding, '
               'handle the emergency: if there is a fire source, use the fire '
               'extinguisher; then go to the base station (navigate only if '
               'not already there); finally close the door.\n'
               'Branch 2: If a victim is present, ask a human for help.\n'
               'Branch 3 (day shift): If it is daytime, patrol two locations '
               'in order: for each of positions A and B, if it has not been '
               'visited yet, navigate there and patrol.\n'
               'Branch 4 (night shift): If it is night, go to the base station '
               '(navigate only if not already there) and charge the robot.')),

    dict(task='CX9_mars_sample',
         conds=['isNight', 'atStation', 'isDay', 'hasSample', 'TargetFound',
                'checkReachable'],
         acts=['foldPanels', 'goToStation', 'charging', 'unfoldPanels',
               'getData', 'send', 'searchTarget', 'goToPos3'],
         tree=sel(seq('isNight', 'foldPanels',
                      sel('atStation', 'goToStation'), 'charging'),
                  seq('isDay', 'unfoldPanels',
                      sel('hasSample', seq('getData', 'send')),
                      sel('TargetFound', 'searchTarget'),
                      seq('checkReachable', 'goToPos3'))),
         desc=('Planetary exploration with a day/night energy policy and a '
               'science routine.\n\n'
               'Night branch: If it is night, retract the solar panels, go to '
               'the base station (navigate only if not already there) and '
               'charge the robot.\nDay branch: If it is daytime, deploy the '
               'solar panels and carry out the science routine in order: '
               'first, if a sample has been collected, transmit the data and '
               'then send the report; second, if a target of interest has been '
               'found, search around the target; third, if the path is '
               'reachable, navigate to position 3 to continue exploring.')),

    dict(task='CX10_commander',
         conds=['lowBattery', 'atCharge', 'alarm', 'hasFire', 'hasVictim',
                'checkReachable', 'empty', 'TargetFound', 'isDay', 'isNight'],
         acts=['goToStation', 'charging', 'useExtinguisher', 'closeDoor',
               'askHelp', 'goToPosC', 'saveVictim', 'goToPosA', 'pickUp',
               'goToPosB', 'placeB', 'goToPos3', 'doTaskA', 'goToKitchen',
               'closeDoor_2'],
         tree=sel(seq('lowBattery', sel('atCharge', 'goToStation'), 'charging'),
                  seq('alarm', sel('hasFire', 'useExtinguisher'), 'closeDoor'),
                  seq('hasVictim', sel('checkReachable', 'askHelp'),
                      'goToPosC', 'saveVictim'),
                  seq('empty', sel('TargetFound', seq('goToPosA', 'pickUp')),
                      'goToPosB', 'placeB'),
                  seq('isDay', 'goToPos3', 'doTaskA'),
                  seq('isNight', 'goToKitchen', 'closeDoor_2')),
         desc=('A mission commander behaviour with strict priorities. Try the '
               'branches in the given order; enter the first branch whose '
               'leading condition holds.\n\n'
               'Branch 1 (power): If the battery is low, go to the charging '
               'station (skip navigation if already there) and charge.\n'
               'Branch 2 (alarm): If the alarm is sounding: if there is a fire '
               'source, use the fire extinguisher; afterwards close the '
               'door.\nBranch 3 (rescue): If a victim is present, check '
               'whether the path is reachable (if not, ask a human for help '
               'first), navigate to position C and rescue the victim.\n'
               'Branch 4 (delivery): If the hands are empty and a target '
               'object has been found, navigate to position A and pick it up; '
               'then navigate to position B and place the object.\n'
               'Branch 5 (day work): If it is '
               'daytime, navigate to position 3 and execute task A.\n'
               'Branch 6 (idle): If it is night, navigate to the kitchen and '
               'close the door.')),
]


# ------------------------------------------------------------------- driver
def build_xlsx(path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'benchmark'
    ws.append(HEADER)
    for t in TASKS:
        ws.append([t['task'], t['desc'], '\n'.join(t['specs'])])
    wb.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-verify', action='store_true',
                    help='skip verifying the reference trees')
    args = ap.parse_args()

    for t in TASKS:
        t['specs'] = build_specs(t)
        n_leaves = len(leaves(t['tree'], set(t['conds']), set(t['acts'])))
        print('{:22s} leaves={:2d} conds={:2d} acts={:2d} specs={}'.format(
            t['task'], n_leaves, len(t['conds']), len(t['acts']), len(t['specs'])))
    build_xlsx(XLSX_OUT)
    print('wrote', XLSX_OUT)

    os.makedirs(TREE_DIR, exist_ok=True)
    for t in TASKS:
        with open(os.path.join(TREE_DIR, t['task'] + '.tree'), 'w',
                  encoding='utf-8') as f:
            f.write(emit_file(t))
    print('wrote {} reference trees to {}'.format(len(TASKS), TREE_DIR))

    if args.no_verify:
        return
    print('\nverifying reference trees (all specs must be true)...')
    bad = []
    for t in TASKS:
        path = os.path.join(TREE_DIR, t['task'] + '.tree')
        rep = g.verify_tree(path, os.path.join(VERIFY_DIR, t['task']))
        ok = rep['status'] == 'pass'
        print('  {:22s} {} ({}/{} specs true)'.format(
            t['task'], 'PASS' if ok else 'FAIL', rep['n_true'],
            rep['n_true'] + rep['n_false']))
        if not ok:
            bad.append(t['task'])
    print('\n{}/{} reference trees pass'.format(len(TASKS) - len(bad), len(TASKS)))
    if bad:
        print('FAILED (excluded from a valid benchmark):', ', '.join(bad))
        sys.exit(1)


if __name__ == '__main__':
    main()
