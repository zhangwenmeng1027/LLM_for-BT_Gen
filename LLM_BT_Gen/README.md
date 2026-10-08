# LLM_BT_Gen — LLM 行为树生成能力实验（BehaVerify 验证闭环）

实验流程（CEGIS 式：生成 → 验证 → 反例反馈 → 再生成）：

```
                ┌──────────────────────────────────────────────┐
 Behaverify_benchmark.xlsx（Task / description / LTL）          │
                │                                               │
                ▼                                               │
      构建 few-shot prompt ──► LLM 生成候选 .tree               │
                │              (prompt_behaverify.txt)          │
                ▼                                               │
      注入规范块（LTL 合同，程序自动替换）                        │
                ▼                                               │
      behaverify nuxmv --generate --do_not_trim --ltl + NuSMV   │
                │                                               │
        全部 is true ──► 成功，保存 final.tree                   │
                │否则                                            │
                ▼                                               │
      反例/错误信息反馈给 LLM ──────────────────────────────────┘
      （最多 --max_rounds 轮）
```

## 文件

| 文件 | 说明 |
|---|---|
| `prompt_behaverify.txt` | few-shot 提示词（文法 + 节点库 + 2 个完整示例），风格仿照 Ltl4BtBot/data/prompt.txt |
| `llm_bt_gen.py` | 实验主程序（读取 xlsx、调 LLM、跑验证、反例反馈循环、基线对比、指标统计） |
| `llm_config.json` | API 配置（base_url / api_key / model / prices 单价表），也可用环境变量 `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL` |
| `results/<task>/round_i.tree` | 每轮候选；`round_i_out/` 为对应验证输出（noce/withbt 基线写在 `results/<baseline>/<task>/` 下） |
| `results/<task>/final.tree` | 验证通过的行为树 |
| `results/summary_<model>_<N>.json/.xlsx` | 每次运行的汇总（full 基线，沿用旧命名） |
| `results/summary_<model>_<baseline>_<N>.json/.xlsx` | noce / withbt 基线的每次运行汇总 |

## 用法

```bash
# 单任务
python llm_bt_gen.py --task ABC3
# 多任务 / 全量
python llm_bt_gen.py --tasks ABC3,charge,isFull
python llm_bt_gen.py --all --max_rounds 5
# 换模型（任何 OpenAI 兼容端点：官方 openai、DeepSeek、智谱等均可）
python llm_bt_gen.py --task ABC3 --model gpt-4o-mini
# 基线实验：每模型重复 5 次（自动写 _1.._5 后缀的 summary）
python llm_bt_gen.py --all --baseline noce   --repeat 5 --model gpt-4o
python llm_bt_gen.py --all --baseline withbt --repeat 5 --model gpt-4o
# 离线管线演示（不调 API：第 1 轮故意给错树，第 2 轮修复；仅 full 基线有效）
python llm_bt_gen.py --task charge --mock
```

## 反馈基线（--baseline）

验证失败后，LLM 在下一轮能看到什么由 `--baseline` 决定：

| 取值 | 失败后反馈给 LLM 的内容 |
|---|---|
| `full`（默认，主方法） | 上一次生成的 BT + 验证器信息（被证伪的规约、NuSMV 反例轨迹，或工具报错） |
| `withbt` | 仅上一次生成的 BT（"上一次不满足规约，请修正"），不给任何验证器信息 |
| `noce` | 无任何失败相关信息，仅按任务信息重新生成（每轮 prompt 与第 1 轮相同） |

## 每任务统计指标

summary json 的每条记录与 xlsx 的每一行包含：

| 指标 | 字段 |
|---|---|
| 是否生成正确的 BT | `Success`（0/1，以验证器全部规约为准） |
| LLM 调用次数 | `LLM Calls`（仅统计成功调用，见下方重试策略） |
| 消耗的总 token 数 | `Prompt` / `Completion` / `Total Tokens` |
| 花费的金额 | `Cost (USD)` = token 数 × `llm_config.json` 的 `prices` 单价 |
| 当前问题解决的时间 | `Time (s)`（该任务总耗时） |
| LLM 调用花费的时间 | `LLM Time (s)`（所有 LLM 调用累计，含失败重试的尝试） |
| 验证器验证花费的总时间 | `Verify Time (s)`（所有 behaverify/NuSMV 验证累计） |

`prices` 按「模型名前缀」匹配（长前缀优先，如 `gpt-4o-mini` 不会被 `gpt-4o` 抢先），
格式为 `"前缀": [输入单价, 输出单价]`（美元/百万 token）。默认值取官方定价，走中转站
时请按实际价格修改；模型没有匹配到单价时 `Cost (USD)` 为空并打印警告。

## LLM 调用限制与出错重试

- 每任务调用上限 `--max_rounds`，默认 **5**；每一轮恰好一次**成功**的 LLM 调用。
- 调用出错（SSL 连接问题、超时、5xx、429 等）**不计入调用次数**：自动指数退避重试
  （5s、10s、20s…最多 6 次尝试，`LLM_MAX_ATTEMPTS`/`LLM_RETRY_WAIT` 可改），重试成功
  则继续当轮；6 次全部失败才判定该任务失败（此时也不消耗次数）。

## 重复实验（--repeat）

`--repeat 5` 在同一命令内把所选任务集完整跑 5 遍，每遍各写一份 summary：

- full 基线：`summary_<model>_<N>.json/.xlsx`（沿用旧命名，N 接着已有编号递增）
- noce / withbt：`summary_<model>_<baseline>_<N>.json/.xlsx`

N 取「该 model+baseline 尚未占用的最小编号」，因此跨命令反复调用也会自动接续成
`_1, _2, _3 …`。`stats.py` 按 model+baseline 分组统计（基线显示为
`gpt-4o [noce]`），不会与 full 混在一起。

## 统计脚本

两个脚本都自动扫描 `results/summary*.json`，按 model（+baseline）分组：

```bash
python stats.py                                # 旧版：解决率 + 1/2/3+ 次调用分布
python stats_avg.py                            # 新版：论文口径的平均值统计（下表）
python stats_avg.py --model gpt-4o             # 只看一个模型（各 baseline 分开成行）
python stats_avg.py --model gpt-4o --baseline noce
python stats_avg.py --out results/result_avg.xlsx
python stat_avg_all.py --last 5               # 总表：全部 (模型 × baseline) 组，mean ± std
```

`stats_avg.py` 输出（控制台 + `results/result_avg.xlsx`，另含 per_task 每任务难度表）：

| 列 | 口径 |
|---|---|
| Avg Solved / Solve % | 每次运行平均解决任务数 / 解决率 |
| Calls/Task* | 每任务平均 LLM 调用次数，**失败任务统一按 10 次计**（`--max-retries` 可改） |
| Calls/Solved | 仅成功任务的平均调用次数（修复效率） |
| Tokens/Task | 每任务平均总 token（失败任务也计入） |
| Cost/Run $ / Cost/Task $ | 跑完一整遍 benchmark 的平均花费 / 每任务平均花费（模型未配单价则 n/a） |
| Time/Solved s | 解决一个任务的平均总耗时（仅成功任务） |
| Time/Task s | 每任务平均总耗时（失败任务也计入） |
| LLM s/Task、Verify s/Task | 每任务平均 LLM 调用耗时 / 验证器耗时 |

`stat_avg_all.py` 是 3×3 总表脚本（仿 BTLTL/PDPL 的 stat_avg_all.py）：自动发现全部
(模型 × baseline) 组，每组按运行文件输出 **mean ± std**（样本标准差，单次运行 std=0），
一次写 4 个 sheet 到 `results/statistics_avg_all.xlsx`——`summary`（"mean ± std" 文本，
可直接进论文）、`mean` / `std`（纯数值，供透视/画图）、`per_run`（长表，每次运行一行，
画箱线图/误差线用）。失败任务统一按 10 次调用计（`--max-retries` 可改）；
`--last 5` 每组只取最新 5 个文件（剔除早期试跑）。

```bash
python stat_avg_all.py --last 5                       # 3 模型 × 3 基线 × 5 次总表
python stat_avg_all.py --model gpt-4o --baseline noce # 单组
```

## 加难版 70 任务 benchmark（Behaverify_benchmark_hard.xlsx）

原 benchmark 太容易的根源（已实证）：规约后件是 `(or, success, failure)` 型，而
fastforwarding 编码下未被 tick 的节点 status=invalid，所以该后件等价于"下一 tick 必
须 tick 到该节点"——但原规约只覆盖部分转移且有些后件恒真（动作不会失败），错误结构
常被放过（如 firefighting 的参考树换掉一个 selector 原规约照样通过）。

`make_hard_benchmark.py` 保留 70 个任务与参考树，把每个任务的规约**整体替换**为从参
考树自动派生的完整契约：entry + 每个叶节点的 success 链/failure 回退 + **重启规约**
（终点转移全部钉死）。70/70 任务强化成功（原 439 条 → 743 条，平均 6.3 → 10.6 条/任
务），全部经真实验证器确认参考树在新规约下 PASS（可解性），扰动测试确认更严
（firefighting 原 pass → 新 fail）。原 xlsx 不改动；结果请写入 results_hard/ 与主
实验隔离。已知局限：ABC3 类 fallback 派发任务，分支 1 的动作恒成功导致后续分支在任
何 env 下都不被 tick，其规约必然空洞（参考树走不到的节点无法约束）——这是原任务
结构设计的固有局限，规约层面无法修复。

```bash
python make_hard_benchmark.py          # 重建并验证（约 5-8 分钟，70 次验证）
# 试点：先跑 1 遍看区分度
python llm_bt_gen.py --all --benchmark ../behaverify/Benchmark/Behaverify_benchmark_hard.xlsx --results_dir results_hard --baseline full --model gpt-4o --repeat 1
# 全量：3 基线 × 3 模型 × 5 次（结果隔离在 results_hard/）
python llm_bt_gen.py --all --benchmark ../behaverify/Benchmark/Behaverify_benchmark_hard.xlsx --results_dir results_hard --baseline noce --model gpt-4o --repeat 5
# 统计（与 results/ 完全隔离）
python stat_avg_all.py --dir results_hard --last 5
python stats_avg.py --results_dir results_hard
```

## 复杂任务 benchmark（10 个 CX 任务，v2.1 加难版）

`complex_tasks.xlsx` 含 10 个高难度任务（CX1..CX10）：叶节点 9–25 个（原 benchmark
5–19）、嵌套至 3–4 层、`_2` 重试/副本节点（唯一命名压力）、六路优先级调度（CX2，
23 叶）、三位置日/夜巡逻（CX4）、25 叶 6 分支任务指挥官（CX10）。树结构由
`make_complex_benchmark.py` 定义，LTL 规约从参考树**自动派生**，且比原 benchmark
更强——在 entry/success 链/failure 回退之外额外加了**重启规约**（根完成后下一 tick
回到首条件，实验验证该语义成立），每个终点转移都被钉死；每任务 14–36 条规约
（原 6–22）。全部参考树经验证器确认 10/10 PASS（可解性证明），扰动测试确认错误
结构会 fail。参考树在 `../behaverify/Benchmark/trees/CX*.tree`（也是 `--mock` 演示
的参照）。

```bash
# 重建 benchmark（含可解性验证，10/10 PASS 才有效）
python make_complex_benchmark.py

# 跑实验：3 基线 × 3 模型 × 5 次，结果隔离在 results_complex/
python run_complex.py                                   # 全组合
python run_complex.py --repeat 1                        # 先跑一遍试点
python run_complex.py --models gpt-4o --baselines noce,withbt
python run_complex.py --max_rounds 5                    # 调用上限（默认 5）

# 统计：3×3 论文总表（mean±std）+ 每组均值 + 每任务难度表
python stat_complex.py                                  # --last 5（默认）
python stat_complex.py --last 0                         # 平均全部已有运行
```

输出：`results_complex/statistics_complex.xlsx`（summary/mean/std/per_run 四个 sheet）
与 `results_complex/result_avg.xlsx`（含 per_task 难度表）。`llm_bt_gen.py` 新增
`--benchmark <xlsx>` 与 `--results_dir <dir>`，其他用法不变。

补配单价后给历史结果回填费用（按文件里已存的 token 数重算，无需重跑实验）：

```bash
python backfill_cost.py    # 处理 results/ 下全部 summary*.json 中为 null 的 cost_usd
```

先在 `llm_config.json` 里填 `api_key`（或 `set LLM_API_KEY=...`）。

> 注意：`call_llm` 用标准库 urllib 直连 OpenAI 兼容端点（不依赖 openai SDK，
> 且绕过系统代理）。若你的网络必须走代理，把 `call_llm` 里的
> `ProxyHandler({})` 改为 `ProxyHandler(urllib.request.getproxies())`。

## 设计要点

1. **提示词**（仿 BTLTL 项目 prompt）：DSL 文法规则 + 条件/动作节点库 +
   2 个完整 few-shot 示例；强调两个硬约束——节点名在树中至多出现一次、
   规约中引用的每个节点必须在树中存在。
2. **规范注入**：LLM 只负责生成行为树；验证合同（xlsx 中的 LTLSPEC）由
   程序在验证前替换进 `specifications` 块，避免 LTL 抄写错误干扰实验。
3. **验证**：`behaverify nuxmv <tree> <out> --generate --do_not_trim --ltl
   --nuxmv_path <NuSMV>`；`--do_not_trim` 必须加（防止结构相同的兄弟子树
   被剪枝导致规约引用失效）。
4. **反馈**：两类信息回传 LLM——生成/语法错误（工具报错原文尾部）与
   被证伪的规约 + NuSMV 反例轨迹摘录，并附语义提示（sequence 遇失败即停、
   selector 遇非失败即成）。

## 依赖与路径

- venv：`D:\科研\LLM_for_BT_Gen\behaverify_venv`（已装 behaverify、openai、openpyxl）
- 模型检验器：NuSMV 2.7.1（`D:\tools_nusmv\...`，`llm_bt_gen.py` 顶部常量可改）
- benchmark：`../behaverify/Benchmark/Behaverify_benchmark.xlsx`





# 运行指令

 1. 指定 LLM 型号

  优先级：--model 参数 > 环境变量 LLM_MODEL > llm_config.json 的 "model" 字段（当前默认 gpt-5.5）。

  python llm_bt_gen.py --task charge --model gpt-4o
  python llm_bt_gen.py --task charge --model claude-sonnet-4-5
  python llm_bt_gen.py --task charge --model gemini-2.5-pro

  也可以逗号分隔一次跑多个模型（依次执行，每个模型各跑完自己的任务集与 --repeat，summary 按模型分开写；API key 按各模型前缀重新匹配）：

  python llm_bt_gen.py --all --model gpt-4o,gpt-5.5 --repeat 5

  注意两点：

  - 所有请求都发到 base_url 指定的 OpenAI 兼容中转端点（当前是 https://4sapi.com/v1，走本地代理 127.0.0.1:6789）。--model 的取值必须是该中转支持的模型名，比如 Claude 要用它认的名字（claude-sonnet-4-5 之类），不是 Anthropic 官方 API 直连。
  - API key 按模型名前缀自动匹配：llm_config.json 里的 keys 配了 gpt / claude / gemini 三个前缀，脚本取 model.startswith(前缀) 对应的 key。所以模型名必须以这些前缀开头才能拿到 key（写 claude-xxx 自动用 claude 的 key，无需手动指定）。也可以用环境变量 LLM_API_KEY 强制指定一个 key，绕过前缀匹配。

  2. 限制 LLM 调用次数（含出错重试说明）

  python llm_bt_gen.py --task charge --max_rounds 3   # 默认 5

  --max_rounds 是每个任务的 LLM 调用上限：每一轮恰好一次成功 LLM 调用（第 1 轮生成，之后每轮修复重生成）。总调用量 ≤ max_rounds × 任务数。没有单独的“全局总调用次数”参数。

  调用出错（SSL/超时/5xx 等）不消耗调用次数：自动指数退避重试（最多 6 次尝试），全部失败才判任务失败。

  3. 跑基线并重复 5 次

  python llm_bt_gen.py --all --baseline noce   --repeat 5 --model gpt-4o
  python llm_bt_gen.py --all --baseline withbt --repeat 5 --model gpt-4o
  python llm_bt_gen.py --all --baseline full   --repeat 5 --model gpt-4o   # 主方法

  --baseline 控制「验证失败后反馈什么」：full = BT+验证器反馈（默认）；withbt = 只给错误 BT；noce = 什么都不给、按任务重新生成。--repeat N 重复 N 遍，summary 自动按 _1.._N 后缀堆叠。

  4. 指定任务

  python llm_bt_gen.py --task charge              # 单个任务（必须与 xlsx 的 Task 列精确一致）
  python llm_bt_gen.py --tasks ABC3,charge,isFull # 逗号分隔多个

  任务名来自 Behaverify_benchmark.xlsx 的 Task 列（如 charge、ABC3、patrol1、pour_drink），大小写要完全匹配。

  5. 批量跑全部任务

  python llm_bt_gen.py --all --max_rounds 5 --out results/summary_batch.json
