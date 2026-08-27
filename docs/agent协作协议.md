<!-- doc: type=contract status=active updated=2026-08-27 -->
# Agent 与 Beacon 协作协议（职责边界 + 协作接口 + 缺口判定准则）

> **定位**：任何「要不要改 Beacon」的判断，先查本协议。本协议是 D-020（Beacon 产完整论文职责）与 D-021（协作梳理）的落地。
> **原则**：先梳理协作，再决定改不改机制——**不"觉得需要就改"**。

## 一、职责边界（谁做什么）

| 方 | 职责 |
|---|---|
| **agent**（外部/Cursor/子 agent） | 前置工作（探索、brief 起草、口径裁决）；**写代码 + 算数据（科学度）**；按方向把明确内容注入体系；问题回查（体系问题 vs 方向/计算问题，互相协作）；评审辅助（读必答项清单、人审） |
| **Beacon** | **产完整论文本体**（骨架 → prose 展开 → 论文）；机械/确定性职责：资产登记+哈希冻结、装配、数字红线（check_paper_numbers）、L4/必答项闸门、口径核查脚本、stage 推演；可复现性（同一登记 → 同一执行） |
| **D 盘** | 只做拆开 + 小改造（Word 化、局部修改）；赛后评估（最终评估报告） |

**对照口径（D-020）**：数据与科学度用 agent 跑的版本；论文本体以 Beacon 产出的作改动依据；遇到问题先判定是哪一方的问题，再决定改谁。

## 二、协作接口清单（已有）

| 接口 | 方向 | 产物/机制 |
|---|---|---|
| `brief.json`（+`brief check`） | agent → Beacon | 方向性内容注入；口径防线校验 |
| `reference add` | agent → Beacon | 求解代码登记 + sha256 冻结（A-13 哈希校验） |
| `reference run/tables/paper` | Beacon | 求解执行 / 交付表装配 / 骨架装配（数字唯一事实源=evidence） |
| `reference expand` | Beacon | 骨架 → 完整论文 prose 展开（A-01，增量数字闸门） |
| `problem.json source_files` | agent → Beacon | 冻结资产登记（T-19） |
| `evidence-package` + `check_paper_numbers --evidence` | agent → Beacon | **任意 md/txt/json 证据文件**提取数字白名单（含 agent 临时脚本产出）——红线覆盖 |
| `stage --json`（`next_command`/`d007_missing`） | Beacon → agent | 推演已完成前缀 + 提示下一步 |
| `review-check` | Beacon → 评审 agent | L4/必答项/数字/gap 机械校验包装 |
| playbook §〇 选型 checklist | agent 用 | 前置智慧选型（双人双读等） |

## 三、缺口判定准则（新需求先问三问）

1. **是机械/确定性职责吗？**（可复现、哈希、装配、闸门）——是 → Beacon 做（且只做机械件）
2. **是红线相关吗？**（数字溯源 / 证据一致 / 口径核查）——是 → Beacon 提供机械校验件（check 脚本）
3. **agent 临时脚本 + 现有接口能否覆盖？**——能 → **不建新机制，写约定**（落盘格式/登记位置/白名单入口）

**判定例（2026-08-27 首例）——清单型表（原 A-08）**：①"装配什么"取决于 agent 输出格式，不可预知 → 非纯机械；②清单数字进论文须红线覆盖 → 红线相关；③`check_paper_numbers --evidence` 已支持任意证据文件，agent 求解脚本落盘清单文件即可进白名单 → 可覆盖。**结论：取消 A-08 机制，改约定**——agent 临时脚本生成清单（正文节选 + 附录全量归 agent/D 盘拼接），清单文件纳入 evidence-package 并作为 `--evidence` 传入。

## 四、已判定的缺口去向（2026-08-27 梳理 · D-021）

| 原任务 | 原定义 | 判定 | 去向 |
|---|---|---|---|
| A-08 / B-01（清单型表） | Beacon 内建清单装配机制 | 三问③=能 | **取消**：agent 临时脚本 + `--evidence` 白名单 + 本协议约定 |
| A-04（数据探查命令/schema） | Beacon 脚手架命令 | ③=能（data_profile.md 已有 D-007 约定+判据） | **降级**：协议承担，不建命令 |
| A-05（探索/对撞/清点机械入口） | Beacon 入口 | ③=能（playbook 协议层） | 保持协议层（人/agent 主持） |
| A-07（子 agent 派发/工作目录） | 体系内派发机制 | ③=能（agent 侧约定） | **降级**：agent 侧约定，若进体系再议 |
| A-10（T-15 必答项注入操作面路径） | 操作面注入机制 | ③=能（C 类五问清单已文档化，评审 agent 读） | **降级**：prompt 层已注入 + agent 读清单 |
| A-11（gap 检查跨题型） | 机械脚本扩展 | ①②=是（口径核查红线） | **保留 P1**：check_gap_trigger 键名可配置化 |
| A-02/A-03/A-12（回退/extract/restart） | 机械命令 | ①②=是（操作面机械职责） | 保留，低优先 |

## 五、agent 临时脚本的参考约定（清单/图/表类产出）

1. **落盘**：清单类产出落盘到 `problems/<题号>/source/` 或 runs 本题目录（命名 `*_list.*` / `*_table.*`），格式 md/txt/json 任意（`--evidence` 均支持）；
2. **登记**：纳入 `evidence-package`（`reference add` 时一并登记，哈希冻结）；
3. **红线**：论文正文引用的清单数字，评审时把清单文件作为 `--evidence` 传入 `check_paper_numbers`；
4. **附录**：正文节选前 N 行 + 全量清单放附录/附件——由 agent 或 D 盘拼接，Beacon 不加工。

## 更新记录

- 2026-08-27 建立（D-021）：从 A-08 质疑梳理而来；判定准则 + 首轮缺口判定落地。
