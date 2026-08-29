<!-- doc: type=decision status=active updated=2026-08-29 -->
# D-026 · coder 一致性接续：执行证据为主

- 日期：2026-08-29（学-12 / 评估 04 / ACT-05）｜ 状态：accepted → 已落地
- 决策编号：07 决策表 D-026

## 背景

评估 04：retry 应喂执行证据（报错/输出/对拍）而非仅审查意见。D-023 后 consistency 不再自动回 coder，只有 `restart --from coder` 会再 generate。彼时 `_consistency_repair_context` 只注入分数 + issues/suggestions；评审侧已有的 curated stdout 未回灌。内层 `MAX_CODE_RETRIES` 已喂 stderr。

## 决策

1. **只改外层接续反馈**：`_consistency_repair_context` 硬信号在前（curated stdout、失败 stderr、hard 红线），审查意见作补充。循环骨架、routing、`MAX_CODE_RETRIES` 不动。
2. **prompt**：`prev_error_kind == "consistency"` 使用标题「一致性停机后的执行证据」，不再误标「stderr 节选」。
3. **优先级**：内层 `prev_err` 仍盖过 consistency 反馈。

## 后果

- 正面：flag 打开后的 restart 路径与学-12 对齐；审查意见仍可见。
- 负面：无 stdout 的旧 artifact 仍主要靠审查补充。
- 兜底：无 primary 代码则不注入（与改前一致）。

## 本轮不做 / 已登记后续

| ID | 内容 | 为何本轮不做 |
|---|---|---|
| （挂账） | 内层 execute↔generate prompt 再改 | 已喂 stderr/prev_code |
| （挂账） | 敏感性 generate↔execute 对称 | 清单只写 coder |
| （挂账） | 无 baseline 时发明第二套对拍 diff | 有 stdout 即喂；无则不强造 |
| ACT-03 | 节点×brief 覆盖矩阵 | **已关账（D-022 兑现 P1）** |

## 备选方案

| 方案 | 否决理由 |
|---|---|
| 完全丢掉 critic 文本 | 评估 04 要求作补充 |
| 连内层/敏感性一起改 | 超范围；内层已有硬信号 |

## 关联

- 学-12；评估 04；ACT-05；D-023 restart；D-024 旗标
- 实现：`nodes/coder.py` `_consistency_repair_context`；`prompts/coder_figure_one.py`
