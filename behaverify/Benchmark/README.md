# BehaVerify Benchmark（源自 BTLTL 项目的 My_benchmark_ok.xlsx）

本目录把 BTLTL 项目的 70 个行为树基准任务改写为 **BehaVerify** 可验证的
benchmark，并为每个任务实际运行了 LTL 模型检验。

## 文件一览

| 文件 | 说明 |
|---|---|
| `My_benchmark_ok.xlsx` | 原始 BTLTL 基准（只读，勿改） |
| `Behaverify_benchmark.xlsx` | 本项目 benchmark（同格式四列 + 结果列） |
| `trees/*.tree` | 70 个任务的 BehaVerify DSL 行为树（含规约） |
| `gen_benchmark.py` | 从原始 xlsx 导出的 JSON 生成 trees/（规约翻译 + 树修复） |
| `make_xlsx.py` | 汇总规约与验证结果，生成 `Behaverify_benchmark.xlsx` |
| `run_verification.py` | 批量调用 `behaverify nuxmv --generate --ltl` 验证 |
| `_benchmark_dump.json` / `_benchmark_new.json` / `_verify_results.json` | 中间产物 |
| `_verify_out/<task>/nuxmv/` | 每个任务生成的 SMV 与 NuSMV 验证输出（证据） |

## 规约改写原则（Task 名与执行逻辑保持一致）

1. **任务名、description 逐字保留**（原第 69 行任务名为空，命名为 `attack2`）。
2. **LTL 逐词翻译**：BTLTL 的节点状态原子 `node_s/_f/_r` 与 BehaVerify 的
   `(success, node)/(failure, node)/(running, node)` 谓词一一对应；
   `X`→`(next, …)`、`G`→`(globally, …)`、`->`→`(implies, …)`、`||`→`(or, …)`。
   原文中每条 `&&` 子句单独作为一条 `LTLSPEC`，便于逐条给出验证结论。
3. **建模约定**：条件叶子 = 环境布尔变量，初始值非确定 `{True, False}`、
   之后冻结（environment_update 自赋值）；动作叶子恒返回 success。
   BT 列用 BehaVerify 记法（selector(...)/sequence(...)）重写。

## 对原始基准的修正（均有据可查，见 gen_benchmark.py 的 PATCHES）

- 原文若干 BT 字符串括号不闭合 / 残缺：`openDoor`（游离的 `'>'`）、
  `alarm5`（缺括号）、`acceptDoOtherTask`（两个顶层列表，按描述"chooses"包成 selector）、
  `evaluate`（描述要求 finally move to parking lot，补 `moveToParking`）、
  `hungry_kitchen`/`pour_drink`（描述的 Task 2 "Seek help"，补 `askHelp`）、
  `attackTarget`（描述"go to position B… eat food"，原文误写 `goToPosA` 且漏 `eatfood`）。
- `roomKnown` 的 LTL 原文有一处括号笔误（`G(invValid_f) -> X(...)`），按上下文修正。
- 同名节点多次出现（BehaVerify 要求节点名唯一）：克隆为 `foo_2`、`foo_3`…，
  规约中该节点的原子命题改为对全部实例的析取。
- `continue` 改名 `continueTask`（避免与常用保留字冲突）。

## 验证结果（NuSMV 2.7.1，2026-09-06）

- **70 个任务、439 条 LTLSPEC：438 条 true，1 条 false。**
- 唯一的反例在 `attackTarget`：
  `G(TargetAdjacent_s -> X(attackTarget_s|f|r))` 为 **false**。
  原因：原始 BT 该处为 `?(TargetAdjacent, attackTarget)`（**选择器**），而任务
  描述与 LTL 都是"检查目标在附近，**然后**攻击"（**顺序**语义）。标准 BT 语义下
  check 成功时选择器短路、attackTarget 不会执行 —— 这是原始基准中 BT 结构与
  描述/LTL 的内在不一致，被 BehaVerify 验证器如实发现。

## 复现步骤

```bash
# 1. 生成 trees（需要原始 xlsx 的导出 JSON）
python gen_benchmark.py
# 2. 批量验证（需 Python 环境装好 behaverify，及 NuSMV/nuXmv 可执行文件；
#    run_verification.py 中 NUXMV 变量指向模型检验器路径）
python run_verification.py
# 3. 生成结果 xlsx
python make_xlsx.py
```

注意：生成 SMV 时必须加 `--do_not_trim`。默认的节点剪枝会把"结构相同的兄弟
子树"当冗余删除（如 ABC3 的 4 个 `?(atPosX, goToPosX)` 分支），导致规约引用
已删节点。这也是 CLAUDE.md 中 `--do_not_trim` 标志的用途。
