
运行基线实验
    python llm_bt_gen.py --all    --repeat 5 --model gpt-5.5
  python llm_bt_gen.py --all --baseline noce   --repeat 5 --model gpt-4o
  python llm_bt_gen.py --all --baseline withbt --repeat 5 --model gpt-4o


claude-opus-4-6


python stat_avg_all.py --last 5                        # 总表：3 模型 × 3 基线，每组取最新 5 个文件
  python stat_avg_all.py                                 # 不加 --last 则平均每组全部文件
  python stat_avg_all.py --model gpt-4o                  # 单模型 3 基线
  python stat_avg_all.py --baseline noce                 # 单基线 3 模型
  python stat_avg_all.py --model gpt-4o --baseline noce  # 精确一组
  python stat_avg_all.py --last 5 --out results/paper.xlsx



 新的加强难度的任务：
 cd D:\科研\LLM_for_BT_Gen\LLM_BT_Gen

  # ① 试点：先跑 1 遍看新规约下的通过率与基线差距
  python llm_bt_gen.py --all --benchmark ../behaverify/Benchmark/Behaverify_benchmark_hard.xlsx --results_dir results_hard --baseline full --model gpt-4o --repeat 1

  # ② 全量：3 基线 × 3 模型 × 5 次（示例一个组合，其余同理）
  python llm_bt_gen.py --all --benchmark ../behaverify/Benchmark/Behaverify_benchmark_hard.xlsx --results_dir results_hard --baseline noce --model gpt-4o,gpt-5.5,claude-opus-4-6 --repeat 5
  python llm_bt_gen.py --all --benchmark ../behaverify/Benchmark/Behaverify_benchmark_hard.xlsx --results_dir results_hard --baseline withbt --model gpt-5.5 --repeat 5

  # ③ 统计（与 results/ 主实验完全隔离）
  python stat_avg_all.py --dir results_hard --last 5
  python stats_avg.py --results_dir results_hard

存储在result_hard中



复杂任务：存储在results_complex中
python run_complex.py --repeat 1    # 试点：看新难度下的通过率
  python run_complex.py               # 全量：3 模型 × 3 基线 × 5 次
  python stat_complex.py              # 统计


   python run_hard.py --models gpt-4o,gpt-5.5,claude-opus-4-6 --baselines withbt --repeat 5
   python run_hard.py --models gpt-4o,gpt-5.5,claude-opus-4-6 --baselines full --repeat 5
   python run_hard.py --models gpt-5.5,claude-opus-4-6 --baselines noce --repeat 5

   python run_complex.py --repeat 4




待运行：
python repair_task.py --round summary_gpt-5.5_1 --results_dir results_hard √
 python repair_task2.py --round summary_gpt-5.5_withbt_2 --results_dir results_hard ---
  python repair_task2.py --round summary_gpt-5.5_withbt_4 --results_dir results_hard ---


 python repair_task.py --round summary_gpt-5.5_withbt_3 --results_dir results_hard ---
  python repair_task.py --round summary_gpt-5.5_4 --results_dir results_hard √