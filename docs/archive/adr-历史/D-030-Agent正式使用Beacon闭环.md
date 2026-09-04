<!-- doc: type=decision status=active updated=2026-09-05 -->
# D-030 · Agent 使用 Beacon 的正式闭环（brief 驾驭图；登记=改代码空间）

- 日期：2026-09-05（用户澄清正式用法）｜ 状态：accepted
- 决策编号：07 决策表 D-030

## 背景

此前若干路径把「agent 本地算完 + 会话写论文 / 只装配骨架」当成结束，或把 `reference add` 理解成「把已写好的代码交进去交差」。学习走查第 4 站 / `agent协作协议` 停在接口清单，**不够描述真实使用闭环**。

用户澄清（正式口径）：

1. 本地 agent 自己跑完全部（探索/编码/算数）**并不意味着结束**。  
2. 然后**启动 Beacon**：用 **brief 引导体系**走到暂定正确的方向。  
3. 可用本地脚本（reference / inject），但 **critic 仍要用**——脚本不行就当要重写；critic 反馈是 agent **手改代码**的依据。  
4. 循环直到图内流程跑通，**自然产出论文**。  
5. 若方向严重偏离 / 代码不可用：由 agent 判断是 **brief 不够全面**，还是 **brief 不如体系产出的方向**（可回改 brief 或采纳体系侧）。  
6. **代码登记的意义**：不是「把之前 agent 写的用上当终稿」，而是给本地 agent **空间发挥改代码能力**，**不再依赖 coder 节点 LLM 生成**，但**仍然以 Beacon（LangGraph）为核心**。  
7. 前面「会话轨 B 当写作终态 / 操作面停在骨架」等方向**不是**这套正式用法；可能含错误决策残留，以本决策为准纠偏。

与 D-029 关系：D-029 解决「写作要接回 writer」；本决策解决「**整题 agent 如何正式使用 Beacon**」——比接桥更大一圈。

## 决策

### 1. 正式闭环（唯一推荐用法）

```text
本地 agent：探索 / 编码 / 算数 / 起草 brief（暂定方向）
        ↓  未结束
启动 Beacon：brief 注入 + 代码登记(reference|inject)
        ↓
LangGraph（coder LLM 默认关）：执行冻结脚本 → … → writer/paper_critic → …
        ↓ critic / 门禁失败
反馈 → agent 手改代码或改 brief → 再登记 / 再跑
        ↓
直到流程跑通 → 体系产出论文 → 人少量改 / accept
```

应急（会话手写 prose、只出骨架）允许，但**不得**写成正式产品用法。

### 2. brief 的角色

- brief = **驾驭体系内方向**的主手柄（已有注入切片：analyst/modeler/coder/writer…）。  
- 可对图内节点做「单独操作 / 分段驱动」，仍以 brief 为方向约束。  
- brief 是**暂定**可证伪方向，不是圣经；证伪后回改 brief 或承认体系侧更优。

### 3. 代码登记的角色（重定义）

| 错误理解 | 正确理解 |
|---|---|
| 把 agent 旧代码交进去交差 | 给 agent **接入 Beacon 的改代码工作区** |
| 登记完就不用再动代码 | 登记后仍可 `--force` / 改 inject，响应 critic |
| 替代整个 Beacon | **替代的是 coder LLM**，不是替代图 |

### 4. LangGraph 节点价值（在本用法下）

| 节点族 | 价值 | 默认 |
|---|---|---|
| coder_generate（LLM） | 低（正要摆脱） | **关**（D-024） |
| coder_execute / consistency | **高**：跑登记代码、对拍、硬信号 | 开 |
| model_critic / paper_critic / blueprint_critic 等 | **高**：失败反馈 → agent 手改 | 开 |
| writer / writer_section | **高**：体系产论文 | 开（经接桥） |
| table_assembler / evaluation / human_review / latex | **高**：收尾 | 开 |
| analyst / modeler | **中**：brief 已强时可弱化或作对照挑战 | 可分段跳过/后置，不删 |
| sensitivity codegen LLM | 低 | 默认关；有 inject 则执行 |

### 5. 工程含义（承接 D-029）

- P0：reference/evidence → state 适配进入图；`--from writer` 或等价「从执行段/写作段起跑」。  
- P0：critic 停机产物（issues/stdout）→ 明确「交回 agent 手改」的交棒格式。  
- P1：重写协作协议与定稿「正式用法」文；归档第 4 站标不足。  
- **不**把「轨 A 无人值守从零 codegen 出赛论文」拉回主线（D-005 仍在）。

## 后果

- **正面**：agent 与 Beacon 分工清楚；图有用法；登记有正确语义。  
- **负面**：须补接桥与交棒工程；旧文档（第 4 站、部分定稿语气）需改。  
- **作废/降权的理解**：本地跑完即结束；登记=交差；写作永远会话层；S9「不用了」。

## 备选方案

| 方案 | 否决 |
|---|---|
| 永久会话写论文，图只装配 | 与「以 Beacon 为核心」冲突 |
| 恢复 coder LLM 为主 | 与少 codegen、本地发挥冲突 |
| 删掉 critic | 失去「脚本不行→反馈手改」闭环 |

## 关联

- D-005、D-008、D-020、D-021、D-024、D-025、D-028、D-029  
- 定稿：`94-Agent正式使用Beacon闭环.md`；`docs/agent协作协议.md`  
- 实验：writer 接桥 PASS（学-27）证明写作段可接；本决策要求整图用法对齐
