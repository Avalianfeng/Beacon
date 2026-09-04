<!-- doc: type=decision status=active updated=2026-08-29 -->
# D-025 · S9 职责切换：inject 通道 + 敏感性 codegen opt-in

- 日期：2026-08-29（学-11 嵌合；ACT-14 / ACT-15）｜ 状态：accepted → 已落地
- 决策编号：07 决策表 D-025

## 背景

D-024 已关掉 coder 默认 LLM 写码。敏感性 `sensitivity_code_generate` 仍默认 `complete()`，与「机制留体系、内容给 agent」不一致。接续除 T-19 哈希锁外，需要一条无哈希的「约定目录丢 .py 即跑」通道，让外部 agent 按协议交代码。

## 决策

1. **ACT-14**：敏感性 codegen 与 coder **共用** `--allow-coder-llm` / `allow_coder_llm()`。只关 `sensitivity_code_generate_node` 的 `complete()`。plan / interpret **仍 LLM**。禁用时 **不硬停**：`sensitivity_phase=done` + 错误串，图继续 writer（degraded）。
2. **ACT-15**：`problems/<题>/source/inject/`（即 `data_dir/inject/`）无 sha256。主入口：`_entry.py` → `main.py` → 唯一 `*.py`（排除 `sensitivity.py`）；须 `main(data_dir, out_dir)`。敏感性脚本固定名 `inject/sensitivity.py`。
3. **优先级**：T-19 命中则完全不看 inject。无 T-19 时 inject → 旗标 LLM → coder 硬停（D-024）。
4. **supporting**：不拓多队列；inject/T-19 均缩成 1 条 primary（一次执行多 PNG 挂 primary）。

## 后果

- 正面：S9 LLM 写码（coder + 敏感性代码）同一旋钮；agent 有契约可交 `.py`。
- 负面：inject **故意无哈希**，弱于 T-19，不可当冻结资产。敏感性无脚本且无旗标时论文常为 degraded。
- 兜底：`MATH_AGENT_*_DETERMINISTIC=1` 仍走模板，不要求旗标。

## 本轮不做 / 已登记后续

| ID | 内容 | 为何本轮不做 |
|---|---|---|
| （挂账） | `sensitivity_plan` / `interpret` 仍 LLM | 不是写求解代码；另案 |
| （挂账） | inject 上 sha256 | 故意弱于 T-19；需要冻结走 T-19 |
| （挂账） | supporting 每图一个 `.py` / 多队列 | 无 supporting 仍能出 paper |
| ACT-05 | flag 打开后的 generate↔execute 反馈换硬信号 | **已落地 D-026**（仅 consistency 接续；内层未再改） |

## 备选方案

| 方案 | 否决理由 |
|---|---|
| 独立 `--allow-sensitivity-llm` | 两旋钮；与「流水线 LLM 写码」职责切换不一致 |
| 敏感性禁用时硬停 END | 敏感性是证据增强不是放行闸；与现 soft 失败不对称 |
| 放宽 T-19 免哈希、不新目录 | 冲淡哈希锁；用户已选并列 inject 目录 |

## 关联

- 学-11；D-021 三问；D-024；D-008/T-19；ACT-14/15
- 实现：`inject_asset.py`、`nodes/coder.py`、`nodes/sensitivity.py`
- 协议：[agent协作协议.md](../agent协作协议.md) `source/inject/` 行；契约 S9
