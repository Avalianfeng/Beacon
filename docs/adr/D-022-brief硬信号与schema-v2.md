<!-- doc: type=decision status=active updated=2026-08-29 -->
# D-022 · brief 硬信号优先 + schema v2 + hard 恒停

- 日期：2026-08-29（用户拍板：C-01～C-04 全做、允许大改）｜ 状态：accepted → 已落地
- 决策编号：07 决策表 D-022

## 背景

全流程分析探查（`全流程分析/brief检查/01–06`）结案：评分点/红线/数据口径在评审与验收侧断供；`evaluation` 死承诺；`redline_rules` 契约写了从未进 schema；S6 裸 dict 与 S9 pydantic 双轨。先前「v1 上可选字段、不改题目 brief」会让 `redline_violations` 对现网 mcm51-c 恒通过，成为第二个死承诺。

## 决策

1. **硬信号落点**：红线 / 数据口径 / 评分点以机器校验或参数传递为主通道；文本注入只承担软约束（方向/讨论点）。
2. **schema v2**：`schema_version ∈ {1,2}`；v2 增加可选 `redline_rules`（及可选 `background_knowledge`，本轮不注入节点）。v1 无规则合法。题目数据源：mcm51-c 升 v2 并写入可机器化规则。
3. **severity 正交**：`hard` 在 S7/S9 无论是否 `--strict` 都阻断/stop；`warn` 默认报告，`--strict` 才阻断。hard 只给高置信类型（`literal_ban` / `result_rule`）；`expr_ban`/`symbol_ban` 默认 warn。
4. **注入表**：`NODE_BRIEF_SLICE` 为有序块列表（header / field / dimension / hook），不是无序字段集合。
5. **S6 与 S9 同一解析器**：`_load_paper_brief` 走 `load_brief`。

## 后果

- 正面：评审侧能机械看见 brief；红线有数据源；注入扩展只改表。
- 负面：mcm51-c brief 升 v2 后旧工具若仍假定 version=1 会失败（由双读测试覆盖）；hard 停机可能增加人工接续次数（对齐学-11）。
- 兜底：无 brief / v1 无规则恒通过。

## 备选方案

| 方案 | 否决理由 |
|---|---|
| v1 上可选 redline_rules、不改题目 brief | 机制无数据源，死承诺 |
| 默认全 WARN + 观察期 | 与学-11 hard 一次停打架 |
| 无序字段元组表 | 块序错位，golden 必挂 |

## 关联

- 全流程分析候选 C-01～C-04；学-11 / 学-12；**ACT-03 P1 已关账**（矩阵见 `全流程分析/brief检查/05-节点brief覆盖矩阵.md`）；**ACT-04 已关账**（evaluation 接线 + SYSTEM 去条件承诺）
- 实现：`src/math_agent/brief.py`、`ops_review.py`、`scripts/check_redlines.py`
