<!-- brief 真实调用检查 · 2026-08-28 建 · 2026-08-29 两轮共 6 路子 agent 探查，待查全部结案，处置已登记 -->

# brief 真实调用检查（探查已结案 · 处置见「决策与处置」节）

> **来源**：用户 2026-08-28 指令——把 scoring_notes 注入问题归类为「对 brief 的真实调用的重新检查」，写入探查内容，**后续要查更多**。
> **2026-08-29 进展**：两轮共 6 路子 agent 并行探查后，用户拍板 C-01～C-04 全做（D-022）。**待查 7 条全部结案**；同日五阶段落地完成（见文末「决策与处置」与 `后续行动清单.md` 第六节）。

---

## 已查：注入矩阵（源码核实 · 2026-08-28）

`src/math_agent/brief.py` 渲染器，按节点裁剪：

| 渲染器 | 字段 | 使用节点 |
|---|---|---|
| `render_full_brief` | 全量（方向/公式/讨论点/红线/图/评分/数据/文献） | analyst、blueprint_critic |
| `render_modeler_brief` | 逐题方向 + 公式注意 + 量纲块 | modeler |
| `render_coder_brief` | 红线 + 公式 + 量纲块 | coder_figure_one（2026-08-29 勘误：主 coder 路径实测不达，见勘误汇总） |
| `render_critic_brief` | 公式注意 + 红线 | model_critic |
| `render_discussions_for_group` | 必答讨论点（按章节分组） | writer_section |
| （无） | — | paper_critic、evaluation |

**已知事实**：
- scoring_notes（评分标准要点）只到达 analyst + blueprint_critic；后续 critic/writer/evaluation 全部收不到。
- evaluation 的 SYSTEM 提示词有「若提供评分细则则逐条核对」分支，但调用方从未传参 → 永久死路径（承诺与行为不一致）。
- mcm51-c 实际 brief.json 12 字段，无 background_knowledge / redline_rules / comparison_baselines（契约理想态 vs 实现落差）。

**子 agent 评估**（`子agent分析/03-scoring_notes注入评估.md`，4 条）：①评分点中段断供（押注 analyst 单点翻译）；②paper_critic/evaluation 把关空转；③evaluation 死路径自欺；④注入裁剪无依据（与防注入公理边界不清）。
备注：S9 流水线视角成立；操作面主路径（S0–S8）下评分点核对职责在 S7 评审环节，严重性缓解；第 3 条与主路径无关。

---

## 已查：操作面 S4–S8 消费路径（2026-08-29 · 详见 `brief检查/01`）

**结论一句话：操作面对 brief 的消费只有两处半——S3 阶段判定只看文件存在；S6 `reference paper/expand` 读 `required_discussions` + `per_question_direction` 两字段；S4/S5/S7/S8 及四个校验脚本零字段消费。**

- **S4 预检**：只把 `brief_path` 字符串回显进 preflight.json（ops_preflight.py:24,73），不读内容；schema 校验在 CLI 加载时完成（cli.py:328-335）。
- **S5 求解验证**：evidence-package / independent-review 与 brief 零接触（ops_verify.py、ops_recertify.py 全文无 brief）。
- **S6 登记装配**：唯一字段消费点——`reference paper/expand` 读 required_discussions（仅 disc-assumptions，进模型假设节）+ per_question_direction（方向一句话，进各问摘要）；⚠️ 交棒命令不显式传 `--brief`（ops_handoff.py:79-81），靠 `problems/<id>/brief.json` 缺省路径隐式命中，brief 放别处则静默降级为【待展开】占位。
- **S7 评审**：与 brief 完全脱钩——`--evidence` 白名单只数证据文件的数字 token（check_paper_numbers.py:98-129），**figure_plan/data_notes 对评审清单零影响**；`check_l4_gates` 虽有 `--brief` 参数（:111,137-142）但 ops_review 从不传（ops_review.py:89-93）→ **操作面死参数**（与 evaluation 评分细则死分支同款）。
- **S8 人审登记**：acceptance.json 只含 paper sha256 + approved，无 brief 关联（ops_accept.py 全文无 brief）。
- **哈希闭环缺口**：brief sha256 只写在 S9 入口 manifest（run/supervise/start）并在 restart 校验；S5–S8 产物（evidence-package/review-report/acceptance）都不带 brief 指纹，无法事后核对「评审/登记时用的 brief 是哪一版」。

---

## 已查：redline_rules 机器可读落地（2026-08-29 · 详见 `brief检查/02`）

**结论：`redline_rules` 是「契约写了 → 拍板不排期 → schema 未落地」的字段；5 个 check 工具零结构消费 red_lines；红线实际执行 = 3 处 prompt 文本注入 + LLM 自觉 + brief_coverage 声称性门禁（只查条目被回应、不查禁令被遵守）。**

- **契约出处明确**：完整 schema（id/target/rule_type/pattern/severity + `redline_violations` 纯函数设计）在 `docs/archive/8-20执行批次/02-批次1-机制工程A-M3红线确定性校验.md:6,18-43`；playbook v3.1 要求「red_lines + 机器可读 redline_rules 双写」（brief-playbook.md:293,310）——但 `docs/实现计划-8-20/README.md:70` 标注「**已拍板不排期**」，M3 说明自评「非阻塞项、建议暂缓」。git 历史佐证：代码目录从未出现该字段。
- **代码实际**：schema 只认 version=1（brief.py:104-110）；pydantic 对注入的 redline_rules 键**静默丢弃**（实测 model_validate OK / hasattr=False，无任何提示）——写了也白写。
- **可机器化占比**（mcm51-c 13 条红线逐条判定）：✅ 直接可机器化 **7/13 ≈ 54%**（rl-leak/rl-result-format/rl-units 等，可映射设计文档既有 rule_type）；⚠️ 部分可机器化 5/13（需血缘/表 schema/人工翻译断言）；❌ 基本靠 LLM 1/13（rl-rainfall 语义类比）。**未落地是排期决策而非技术障碍**。
- **弱保证落点**：B16 实证风险原样保留（K_avg=0.1783 违反禁整体 K 红线，LLM 评审仍 8 分压线放行，8-26-M3红线机器化说明.md:25-26）。

---

## 已查：brief_coverage 门禁真实行为（2026-08-29 · 详见 `brief检查/03`）

**结论：门禁全链成立（生成→校验→重试→硬停），4 个真实 run 全部实际全量覆盖；deviated 路径与 retry/stop 分支从未被真实触发。**

- **勘误（重要）：mcm51-c brief 实际 51 条带 id 条目，不是 40 条。**「40 条」是三处错误的叠加：①mcm51-a 的 brief 恰为 40 条（口径串台，git commit 7bb3bfc「M6 brief 1.2-reg-coef(40条)」指 mcm51-a）；②`insight.py:456` `_jsonable` 把列表截断到前 40 项，refA 的 steps/ 产物恰好显示 40 条（记录截断，checkpoints.sqlite/final_state.json 真值 51）；③mcm51-c brief git 历史（47→51）从未是 40。CLI 权威值：`brief check` 输出 51 条（cli.py:2244 实跑验证）。
- **行为链**：analyst prompt 强制逐条回应（prompts/analyst.py:17-20，禁止「总体遵守」）→ blueprint_critic 评审含 brief_coverage 检查项（blueprint_critic.py:11-12,52）→ `routing.after_blueprint_critic` 先跑确定性 `brief_coverage_problems`（routing.py:29-36；brief.py:174-195：缺条目或 deviated 无理由 → 记问题）→ 有问题 → retry（`MAX_BLUEPRINT_ITERATIONS=2`，config.py:53，最多一次 retry）→ 耗尽 → **stop 硬停**；门禁先于 approved 判断，不依赖 LLM。
- **真实产物**（runs/ 全量扫描 4 个带 brief run）：refA **51/51** 全 followed（steps 显示 40 是 `_jsonable` 截断）；mcm51-b 52/52；mathorcup16 25/24（多 1 条幻觉 id「参考文献方向」，门禁不查多余 id → 放行）；51mcm-a 39/40 缺 `1.2-reg-coef` 但**漏检**——运行时是门禁 commit（3e97a20）之前的旧代码（上线时序事故，非逻辑缺陷）。门禁上线后从未经历真正的失败演练。
- **附带发现**：①门禁 retry 无「缺哪些 id」定向反馈——analyst 只在 critic 未通过时收到反馈（nodes/analyst.py:24-27），gate 缺口触发的 retry 收不到定向修单信息；②`insight.py _jsonable` 的 `[:40]` 截断污染步骤产物可审计性（凡列表 >40 项的字段都受影响，不止 brief_coverage）；③门禁不拦 coverage 幻觉 id（单向检查盲区）。

---

## 已查：background_knowledge 缺失影响面 + 校验范围（2026-08-29 · 详见 `brief检查/04`）

**结论：background_knowledge 缺失 = 「契约字段 + 注入点双重未落地」；实际损失被 reference_direction + per_question_direction 内嵌知识 + problem background 部分对冲，但「领域因果链/机制」的显式注入通道确实不存在。**

- **契约出处**（全仓 grep 18 处，src 零命中）：`docs/内外全流程总纲.md:103`（S2 必须产出领域知识.md 并写入 brief）、`docs/实现计划-8-20/8-27-操作面契约.md:162`（已有字段，不新造 RAG）、`docs/brief-playbook.md:6,13,315`、`docs/8-27-完整图景/05-题目档案.md:21`（H-01 缺（不补））。**注入点本身也是未决的**（`用户建议与体系缺口.md:26`：注入点候选待定）。
- **替代物实测**：`reference_direction` 8 条只达 analyst/blueprint_critic（brief.py:256-258 唯一渲染点），且是「方法族关键词」层面，不含因果链；RAG 与 brief 零耦合且默认关闭（config.py:100 `MATH_AGENT_RAG_ENABLED` 默认 0，runs/rag.sqlite 不存在）；`problems/mcm51-c/领域知识.md` **存在且内容完整但无注入通道**。
- **影响面分级**：高 = analyst/blueprint_critic（缺因果链显式块）；中 = modeler/coder/model_critic（本就不收 reference_direction，知识经 direction 间接转述）；低 = writer 参考文献（select_references 独立于 brief，但 reference_direction 也不达 writer）；风险点 = paper_critic（不收 brief 任何字段，无领域知识/无评分细则/无文献对照）。
- **校验范围表**（WARN vs 阻断）：硬阻断 = JSON 坏/version≠1/必填缺/类型错/id 重复/sections 超白名单；仅 WARN = problem_id 不匹配、brief 全空；**静默通过 = extra 未知字段丢弃（background_knowledge 等写了也无声吞掉）、空 brief、内容质量**；`paper` 命令走宽松路径（仅 JSON 可解析性，无 schema 校验）；门禁盲区 = `reference_direction` 无 id 不进门禁，文献方向写了 8 条也没有「analyst 必须回应」的确定性校验。
- **与既有登记的关系**：缺口 C 已实锤（ACT-08 领域知识注入落实），本次探查补齐了影响面证据链。

---

## 已查：节点 × brief 覆盖矩阵（2026-08-29 · 详见 `brief检查/05`）

**结论：8 字段 × 12 节点 = 96 格中 ✅34 / ⚠️25 / ❌36 / ➖1；断供集中在四个硬约束字段（scoring_notes/red_lines/data_notes/figure_plan）的评审与验收侧（evaluation/paper_critic/S7/figure 生成链），全部有「本该有用」的理由。**

- **断供点 10 条**（05 报告 §三），🔴 硬级 6 条：D1 scoring_notes→evaluation（死承诺）、D2 scoring_notes→paper_critic/S7（评分点齐备性无人核对）、D3 red_lines→S7/产物校验（B16 实证仍压线放行）、D4 **data_notes→主 coder**（数据注意不达写代码的节点，仅经 blueprint 转述）、D5 figure_plan/data_notes→S7、D9 门禁只查「id 被回应」不查「禁令被遵守」（结构级）。
- **硬约束落点候选**（05 报告 §四，P1 三项最小改进）：① scoring_notes 接线 evaluation（极小改动兑现承诺，与 ACT-04 同）；② red_lines 产物校验最小版（M3 已有设计，≈0.5–1 天）；③ data_notes 文本补注 render_coder_brief（一行级）。

---

## 已查：注入架构模块化评估（2026-08-29 · 详见 `brief检查/06`）

**结论：值得做「最小声明式收敛（方案 A：`NODE_BRIEF_SLICE` 表 + 通用 `render_slice`）」，不值得注册制（B）与一等输入对象管线（C）。**

- **真耦合 2 处**：CP1 节点→渲染器映射散落在 6 个 prompts 文件（每处「if brief + 局部 import + 拼块」三件套，新增消费节点要手改 3–4 处且漏改静默）；CP2 字段清单三处各自维护 + 渲染循环双写（加字段要同步 4–6 处，pydantic extra=ignore 使漏改永不报错）。伪耦合/可接受现状 4 处（CP3 check 聚合写死但低频、CP4 state、CP5 门禁清单、CP6 CLI 双轨加载）。
- **推荐方案 A 的理由**：改动频率低（schema v1 冻结、M3 不排期、S9 节点使用率在重估），B/C 的扩展性溢价兑现不了；只有 A 满足「渲染输出逐字符不变 + 单测零破坏」的兼容约束（无 brief 恒通过语义是硬约定）。
- **三缺口改造归属**：①S7 纳入 figure_plan/data_notes → check 聚合声明化 + `scripts/check_brief_claims.py` + review-report 记 brief_sha256（补哈希闭环缺口）；②门禁定向反馈 → routing 写 state 新字段 + analyst 合并注入（独立于 A）；③`_jsonable` 截断 → insight 层独立修（实测已污染 code_artifacts=88、errors=47、brief_coverage=51 三个字段）。

---

## 勘误汇总（2026-08-29 · 全部已回改）

| 位置 | 原表述 | 更正 | 状态 |
|---|---|---|---|
| 本文档「已知事实」 | mcm51-c「12 字段」 | 12 字段无误，但条目数 40 系误传，实为 **51 条带 id 条目**（见门禁节） | ✅ 已改 |
| `03-第2站-操作面S0-S3.md:37` | 「真实形态（mcm51-c 40 条）」 | 51 条 | ✅ 已回改 |
| `08-第5站-真实案例走查.md:14` | 「brief.json（40 条，12 字段）」 | 51 条 | ✅ 已回改 |
| `05-第2站-操作面S6-S8.md:82` | 「S3 brief（40 条压缩注入物）」 | 51 条 | ✅ 已回改 |
| `子agent分析/04-brief注入与coder循环评估.md:7` | 「唯一必须覆盖全 40 条的产物」 | 51 条 | ✅ 已回改 |
| `后续行动清单.md` 第五节 | 「brief_coverage 门禁（40 条逐条覆盖）」 | 51 条，且该项已查结 | ✅ 已改 |
| 本文档「注入矩阵」表 | coder、coder_figure_one 两个消费点 | 实为 coder_figure_one 单点（prompts/coder.py 无 brief 参数且未被调用，nodes/coder.py:718）；baseline/frozen 分支零 brief（`brief检查/05` §一.1） | ✅ 已改 |

> 说明：「12 字段」（8 内容 + schema_version/problem_id/created_at/source）的表述本身是对的；错的是「40 条」条目数。2026-08-29 用户拍板全部回改，已执行。

---

## 决策与处置（2026-08-29 用户拍板 → 已实施）

> 待查全部结案后，用户逐一决策：**四项全做、允许大改**（推翻先前「登记留档、暂不实施」）。正式登记见 `后续行动清单.md` 第六节「正式 ACT」与 [D-022](../docs/adr/D-022-brief硬信号与schema-v2.md)。

| 候选 | 内容 | 用户决策 | 实施 |
|---|---|---|---|
| C-01 | **brief 注入模块化方案 A**（NODE_BRIEF_SLICE 表 + render_slice） | 选定方案 A，全做 | **已落地**：有序块表 + golden 逐字符 |
| C-02 | **S7 评审纳入 brief**（check 聚合声明化 + check_brief_claims.py + review-report 记 brief_sha256） | 全做 | **已落地**：`review-check --brief` |
| C-03 | **P1 三项 + schema v2 + 红线双端**（scoring/data_notes 切片、redline_rules、hard 恒停） | 全做 | **已落地**：mcm51-c 升 v2 七条规则 |
| C-04 | **两个独立小修**（`_jsonable` 截断修复 / 门禁 retry 定向反馈） | 全做 | **已落地** |

**已执行的处置**：C-01～C-04 代码+测试+mcm51-c 数据源；`background_knowledge` 仍不注入节点（ACT-08）。

**后续建议（2026-08-29 · 尚未执行）**：①真实案例冒烟（5 处 prompt 变更不可单测；顺带收集红线 warn 观察期数据）；②ACT-02 重试哲学改造（与本次 hard→stop 强协同）；③ACT-01 coder 重估（依赖本次事实：prompts/coder.py 只剩 SYSTEM）；④S0–S3 走查（独立可开）。详见 `后续行动清单.md` 第六节后。

---

## 待查清单（全部已结案 · 2026-08-29）

- [x] brief 其余字段在操作面 S5/S6/S7 的真实消费路径 → **已查**（`brief检查/01`）
- [x] `redline_rules` 机器可读形式为何未落地、check 工具是否消费 red_lines → **已查**（`brief检查/02`，已拍板不排期）
- [x] `background_knowledge` 字段缺失的实际影响面 → **已查**（`brief检查/04`，与 ACT-08 合并处置）
- [x] brief_coverage 门禁与 40 条逐条覆盖的真实行为 → **已查**（`brief检查/03`，实为 51 条）
- [x] brief check 的校验范围（哪些字段只 WARN 不阻断）→ **已查**（`brief检查/04` §3）
- [x] 节点 × brief 子集覆盖矩阵（ACT-03 最小改进面）→ **已查**（`brief检查/05`：96 格 ✅34/⚠️25/❌36，断供 10 条，P1 最小改进三项）
- [x] S7 评审清单是否应纳入 figure_plan/data_notes → **已查**（`brief检查/05` D5 + `brief检查/06` §三：归属 check 聚合声明化 + check_brief_claims，改动方案已给出）
- [x] 门禁 retry 的「缺哪些 id」定向反馈通道缺失的影响实测 → **已查**（`brief检查/06` §三②：归属路由/状态层，routing 写 state + analyst 合并注入，与模块化方案独立）
- [x] `insight.py _jsonable` 列表截断（`[:40]`）对步骤产物可审计性的污染面 → **已查**（`brief检查/06` §三③：实测污染 code_artifacts=88、errors=47、brief_coverage=51，insight 层独立修）

---

## 追加记录

- **2026-08-29 · C-01～C-04 已实施**：五阶段落地（表驱动 / 切片加宽 / schema v2+S6 / 红线双端+sha256 / 收尾）；mcm51-c `brief.json` 升 v2 并写入 7 条 `redline_rules`。
- **2026-08-29 · 用户决策登记**：四类改造先「登记留档、暂不实施」，同日改拍「四项全做」（候选 ACT C-01~C-04），见上「决策与处置」节与 `后续行动清单.md` 第六节；勘误回改已执行。
- **2026-08-29 · 第二轮两路探查完成**：`brief检查/05-节点brief覆盖矩阵.md`（断供 10 条 + P1 落点候选）、`06-注入架构模块化评估.md`（推荐方案 A，不推荐 B/C；三缺口改造归属）。新勘误：coder 注入实为 coder_figure_one 单点。
- **2026-08-29 · 第一轮四路探查完成**：`brief检查/01-操作面S4-S8-brief消费路径.md`、`02-redlines机器可读落地检查.md`、`03-brief_coverage门禁真实行为.md`、`04-background_knowledge缺失与校验范围.md`；待查前五条结案。
- **2026-08-28 · evidence-package 无文件列表字段（约定 vs 实现落差）**：agent协作协议 §五 2 写「清单文件纳入 evidence-package（reference add 时一并登记，哈希冻结）」——但实际 `evidence-package.json` 结构只有 version/problem_id/solver/evidence_path/checks/ok，**无文件列表字段**。mcm51-c 的 `q3_table3_2.csv` 实际未进登记，白名单靠 S7 评审时手动 `--evidence` 传参。约定写了但实现未落地（与 background_knowledge 同款问题）。处置：用户确认「记录即可」。
