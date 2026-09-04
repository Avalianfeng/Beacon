<!-- doc: type=decision status=active updated=2026-09-04 -->
# D-029 · 本地编码接入体系；写作目标形态 = evidence → writer 链

- 日期：2026-09-04（用户架构纠偏）｜ 状态：accepted
- 决策编号：07 决策表 D-029

## 背景

cumcm23-c 在 expand 失败后用**会话层轨 B**写出 `paper-prose.md`（学-25）。这证明了「语义化 evidence + 受控写作」可行，但**不是**对 graph 内 `writer → writer_section → paper_critic → …` 的废弃。

用户澄清原设想（与学习走查第 3 站一致）：

1. **降低 coder 的 LLM 调用**（D-024 / T-19 / inject）——本地把代码写好、算清，再登记进体系。
2. **本地为整个流程服务写代码**，产物接入 Beacon（`reference` / `frozen_asset` / `inject`），**不破坏 LangGraph 的逻辑与价值**。
3. 各节点（含 writer、paper_critic、table_assembler、evaluation、checkpoint）在走查里各自有价值；缺的是「为体系服务」的用法，不是删节点。

实际发生的错位：

| 层 | 发生了什么 |
|---|---|
| 代码 | LangGraph **未拆**；writer 链完整；`restart --from` **目前只支持 coder**（尚无从 writer 接续的正式入口） |
| 决策误读 | D-005「S9 非默认主路径」被读成「图不用了」；学-25 轨 B 落地被读成「写作改会话层永久替代」 |
| 用法 | 操作面停在骨架/expand；有冻结 reference 也未喂进 writer；会话手写 prose 当终态 |

D-020 原文已要求「操作面接入 writer 能力」；D-028 已列 writer 链为通路之一，但学-25 实操未接桥。

## 决策

1. **不废弃 LangGraph / writer 链。** D-005 只禁止把无人值守全图宣传为已验证出赛主路径；**不禁止**、且**应当**在本地求解就绪后接入图的写作与评审段。
2. **目标工作流（为体系服务）**：
   ```text
   本地研究/编码（少 LLM codegen）
     → reference add / T-19 或 source/inject（确定性执行）
     → 语义化 evidence（轨 B 的 evidence.md 形态，可复用）
     → 【接桥】注入/适配进 MathModelingState
     → writer → writer_section → paper_critic → table_assembler → …
     → review-check / 人审
   ```
3. **轨 B 会话手写**：定位为**验证协议 + 应急落地**（本题已用），**不是**写作层的终态产品形态。协议中「evidence 语义化 + 零编造闸门」必须保留并喂给 writer。
4. **expand**：仍为可选填槽试作；失败后优先**接桥进 writer**，其次才会话轨 B 应急。
5. **工程优先级**（本决策授权排期，本轮不要求一次做完）：
   - P0：`restart --from writer`（或等价：从 reference 产物构造 state 后从图写作段起跑）；
   - P0：reference / evidence.md → writer 可消费输入的适配（输入桥）；
   - P1：paper_critic 与操作面 `review-check` 的职责对照文档化，避免双轨互踩；
   - P1：定稿/契约写清「为体系服务」checklist（本地算完必须登记，写作优先走 writer）。

## 后果

- **正面**：与走查第 3 站、D-008 frozen_asset、D-020「接入 writer」对齐；checkpoint/分节/critic 资产重新有用法。
- **负面**：需实现输入桥与 `--from writer`；在桥未通前，会话轨 B 仍可应急（须标明非终态）。
- **保留**：D-005（不全图无人值守当默认）；D-024（coder LLM 默认关）；D-028（完整初稿职责、禁批骨架）。
- **升格**：整题 agent–Beacon 用法见 **D-030**（本决策只管写作接桥）。

## 备选方案

| 方案 | 否决理由 |
|---|---|
| a. 正式废弃 writer，写作永久会话轨 B | 与用户原设想冲突；丢掉分节 checkpoint / paper_critic / 可测试执行面 |
| c. 长期维持「writer 代码在、用法永远会话」 | 隐性废弃，继续缺「为体系服务」 |
| 把无人值守全图改回默认主路径 | 与 D-005 冲突 |

## 关联

- 相关：D-002、D-005、D-008、D-020、D-024、D-025、D-028；学-25（本题应急）；学习走查第 3 站
- **整题正式用法**：见 **D-030**（登记=改代码空间；本地跑完≠结束；critic→手改）
- 后续验证：cumcm23-c 冻结资产 + evidence.md → 从 writer 起跑对照 `paper-prose.md`
