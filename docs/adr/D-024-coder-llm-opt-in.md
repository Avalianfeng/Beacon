<!-- doc: type=decision status=active updated=2026-08-29 -->
# D-024 · coder LLM 默认关（opt-in）

- 日期：2026-08-29（学-11 ① / ACT-01）｜ 状态：accepted → 已落地
- 决策编号：07 决策表 D-024

## 背景

操作面主路径是 S0–S8，求解代码由人/外部 agent 写（D-005）。S9 在无 T-19 冻结资产时仍默认 `coder_generate` → `complete()`，与学-11「coder 必要性重估」冲突。T-19（D-008）已覆盖「参考实现已登记」的零 LLM 执行。

## 决策

1. **默认硬停**：无冻结资产且未显式允许时，`coder_generate` **不调用** `complete()`；`coder_phase=done`，错误串 `coder: LLM generate disabled; register T-19 or --allow-coder-llm`。
2. **逃生口**：`--allow-coder-llm`（`run` / `start` / `supervise` 转发）或 `MATH_AGENT_ALLOW_CODER_LLM=1`；写入 state `allow_coder_llm`。
3. **接续**：T-19、`source/inject/`（D-025）或开旗标。
4. **本轮只动** `nodes/coder.py` 的 LLM 生成。T-19 与 `MATH_AGENT_CODER_DETERMINISTIC=1` 不要求旗标。

## 后果

- 正面：S9 默认不再偷偷 LLM 写码；与 D-005 / 学-11 一致。
- 负面：无参考实现的 `run`/`supervise` 会停在 coder；旧烟测须加旗标。
- 兜底：敏感性 codegen 与 inject 通道见 **D-025**；flag 打开后的 execute 反馈仍是旧内容（ACT-05）。

## 本轮不做 / 已登记后续

| ID | 内容 | 状态 |
|---|---|---|
| ACT-14 / ACT-15 | 敏感性 codegen 默认关 + `source/inject/` | **已落地 D-025** |
| ACT-05 | flag 打开后 generate↔execute 喂执行证据而非仅审查意见 | 仍开 |
| （挂账） | `_missing_baseline_items` 仍恒 `[]` | 勿当已删 |

## 备选方案

| 方案 | 否决理由 |
|---|---|
| A 彻底移除 LLM 生成、不留 flag | 无人值守烟测无逃生口，回滚成本高 |
| C 维持无参考仍默认 LLM | 与学-11 / D-005 产品叙事冲突 |
| 连敏感性一并关死且不留 flag | 超范围；下游论文链会立刻断 |

## 关联

- 学-11 ①；ACT-01；D-005；D-008/T-19；D-023（门禁一次停仍适用）
- 实现：`config.allow_coder_llm()`、`nodes/coder.py`、`cli.py` `--allow-coder-llm`
- 后续：全流程分析清单 ACT-14 / ACT-15；图景 03 A-17 / A-18
