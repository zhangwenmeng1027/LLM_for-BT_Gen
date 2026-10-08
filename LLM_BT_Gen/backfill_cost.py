# -*- coding: utf-8 -*-
"""回填 summary*.json 里为 null 的 cost_usd：按文件中已记录的 token 数和
llm_config.json 当前的 prices 单价重算，历史实验无需重跑即可补出费用。

典型场景：跑实验时模型还没配单价（警告 "no price configured"），事后在
llm_config.json 补上价格，再执行本脚本即可。

用法:
  python backfill_cost.py                     # 处理 results/ 下全部 summary*.json
  python backfill_cost.py --results_dir results
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import llm_bt_gen as g                                   # 复用价格表逻辑


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--results_dir', default=os.path.join(HERE, 'results'))
    args = ap.parse_args()
    cfg = g.load_config()

    total_fixed = 0
    for path in sorted(glob.glob(os.path.join(args.results_dir, 'summary*.json'))):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print('skip unreadable {}: {}'.format(path, e))
            continue
        model = data.get('model') or ''
        price = g.price_for(cfg, model)
        fixed = 0
        for r in data.get('results') or []:
            if r.get('cost_usd') is not None:
                continue                                  # 已有费用，不动
            if not price:
                break                                     # 该模型仍无单价，整文件跳过
            p = r.get('prompt_tokens') or 0
            c = r.get('completion_tokens') or 0
            r['cost_usd'] = round(p / 1e6 * price[0] + c / 1e6 * price[1], 6)
            fixed += 1
        if fixed:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        total_fixed += fixed
        print('{:44s} model={:16s} filled={:3d} {}'.format(
            os.path.basename(path), model, fixed,
            '' if price else '(no price, skipped)'))
    print('\n{} cost value(s) filled'.format(total_fixed))


if __name__ == '__main__':
    main()
