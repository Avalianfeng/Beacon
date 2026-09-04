# 04 · background_knowledge 缺失与校验范围（只读核查 · 2026-08-29）

> 任务：核查 brief 契约理想态三字段（background_knowledge / redline_rules / comparison_baselines）中 background_knowledge 缺失的实际影响面；brief 校验的 WARN/阻断范围。
> 方法：全仓库 grep + 源码逐点核对 + 运行时实测（pydantic 行为）；只读，未改动任何文件。
> 实证 = 代码/数据/实测；标注「推测」处为推断。

---

## 1. 契约出处：background_knowledge 原文与设计意图

全仓库 `grep 'background_knowledge'` 命中 **18 处，全部在 docs/ 与 全流程分析/（分析文档），src/ 零命中**（连 schema 定义都没有）。

**契约原文出处（记录 文件:行号）：**

| 出处 | 行号 | 表述 |
|---|---|---|
| `docs/实现计划-8-20/00-新题上线流程设计.md` | :26 | 背景通识 + 专业 + 每题方向知识 → brief 字段 `background_knowledge`（来源分级：official_standard > human > model_draft） |
| 同上 | :36 | 资产目录：`brief.json # 前置信息（8 字段 + background_knowledge）` |
| `docs/内外全流程总纲.md` | :103 | 「d 领域知识注入 | S2 必须产出 `领域知识.md`（联网核查术语/典型模式/陷阱），并写入 brief 的 background_knowledge | S2 完成判据（D-007）」 |
| `docs/实现计划-8-20/8-27-操作面契约.md` | :162 | S2：「领域知识核查为强制（D-007）…产出 `problems/<题号>/领域知识.md`，并写入后续 `brief.json` 的 `background_knowledge`（**已有字段，不新造 RAG**）」 |
| 同上 | :195 | S3 产出：「brief.json（八字段 + 可有 `background_knowledge` / `redline_rules`）」 |
| `docs/brief-playbook.md` | :6 | v3.1：「领域知识短卡片写入 `brief.json` 的已有字段 `background_knowledge`，不新造 RAG」 |
| 同上 | :13 | 「产出物 = …`brief.json`（八字段 + `background_knowledge` + `redline_rules`，注入流水线）」 |
| 同上 | :315 | 字段表：「`background_knowledge` = 领域常识 + 专业背景 | 来源分级标注（human/model_draft）」 |
| `docs/8-27-完整图景/05-题目档案.md` | :21 | 「d 领域知识 | S2 产出 领域知识.md 并写入 brief background_knowledge | ✅ | ❌（H-01）| 缺（不补）」 |
| `docs/实现计划-8-20/07-待决策与超范围.md` | :52 | D-007 决策登记（同上内容） |

**设计意图**：`全流程分析/03-第2站-操作面S0-S3.md:79` 给出了最明确的意图表述——「**模型不认识『孔隙水压力→有效应力→抗滑力』这条因果链，不注入就容易外行**」；「从哪来：领域知识.md」。即：**背景知识是注入给流水线 LLM 的**（建模方向的兜底常识），源头是 S2 探索产物 `领域知识.md`（`problems/mcm51-c/领域知识.md` 确实存在，见 §2）。

**注意**：契约从未定义注入到**哪个/哪些节点**。`全流程分析/用户建议与体系缺口.md:26` 只写了「注入点候选=background_knowledge → prompt 注入位」——**注入点本身也是未决的**。所以这是「字段未定义 + 注入点未定义」双重落差。

---

## 2. 替代物核查：没有 background_knowledge 时靠什么

### (a) `reference_direction`（mcm51-c 8 条）—— 部分承担，但只到 analyst/blueprint_critic

- 消费点**唯一**：`render_full_brief`（`src/math_agent/brief.py:256-258`）→ 注入 `analyst`（`src/math_agent/prompts/analyst.py:87-88`）与 `blueprint_critic`（`src/math_agent/prompts/blueprint_critic.py:33-34`）。
- mcm51-c 8 条实测内容（`problems/mcm51-c/brief.json`）：结构变点（PELT/BinSeg）、小波去噪、插补、MAD/IQR 异常、CCF 滞后、贡献度分解、分阶段回归、**Saito 速度倒数 / Voight 准则**——最后一条本质就是领域知识。与 `全流程分析/用户建议与体系缺口.md:24` 一致：「部分内容被压进 reference_direction（如 Saito/Voight 准则）」。
- 但它是「方法族关键词」层面，**不含因果链/机制解释**（如「降雨→入渗→孔压→有效应力→抗滑力」）；且**不达 modeler/coder/model_critic/writer/paper_critic**（各渲染器字段范围见 `brief.py:289-330`：modeler=方向+公式、coder=红线+公式、critic=公式+红线，均无 reference_direction）。

### (b) RAG（`src/math_agent/rag/`）—— 独立通道，与 brief 零耦合，且默认关闭

- `grep 'brief' src/math_agent/rag/*.py` **零命中**——RAG 不读 brief。
- 实际通道：analyst / modeler / writer 三节点调 `rag.retrieve.search`（`src/math_agent/nodes/analyst.py:7-30`、`nodes/modeler.py:13,48`、`nodes/writer.py:37,73,396`），语料 = 离线 ingest 目录（.md/.txt/.pdf → sqlite-vec，`rag/ingest.py`、`rag/store.py`），query = `state.problem`。
- **当前实际未启用**：`src/math_agent/config.py:100` `RAG_ENABLED = os.getenv("MATH_AGENT_RAG_ENABLED", "0") == "1"`（默认关）；`runs/rag.sqlite` 不存在（实测 ls 无此文件）。→ 理论上可把 `领域知识.md` ingest 进语料补领域知识，但当前既未启用、也与 brief 无耦合，**不能视为 background_knowledge 的替代物**。

### (c) analyst / paper_critic 的独立知识渠道

- **analyst**：`build_prompt(..., retrieved_context, ..., brief)`（`prompts/analyst.py:75-88`）→ 知识输入 = RAG（未启用）+ brief 全量（含 reference_direction）+ `# 背景`（problem.json 的 background 字段，318 字符）。
- **paper_critic**：`nodes/paper_critic.py:117-126` 实参只有 paper / 图表数 / 敏感性数 / stdout / model_critic / consistency / figures / sensitivity_runs——**无 brief、无 RAG、无参考文献**。评审标准是通用评委 SYSTEM 提示词（`prompts/paper_critic.py:5-50`），唯一知识类输入是「代码运行真实输出」事实源。**文献/领域知识零渠道**。
- **writer**：`nodes/writer.py:385-389` references 分组调 `tools/references.select_references`（Semantic Scholar API → 失败降级 `references/builtin_library.json` 静态库，`tools/references.py:14`、`tools/scholar.py:21`）——**与 brief 完全独立**，`reference_direction` 也不达 writer（见 §2a）。

### (d) references / scholar —— 文献通道，独立于 brief

- `src/math_agent/references/builtin_library.json` = 静态文献库（seed 条目，queueing/time series/optimization 等通用域）；`tools/references.py` + `tools/scholar.py` = 选择器。均只服务 writer 的参考文献章节，不读 brief 任何字段。

### 隐性补位通道（重要）

- **`per_question_direction` 内嵌了大量领域知识**：mcm51-c 6 条 direction 实测含「降雨→入渗→孔压→位移滞后链」「爆破空值=非事件」「增量口径防虚高 R²」等，`problem.json` 的 `background`（318 字符）含「三段式形变」「监测要素清单」泛化背景。即：**领域知识以「方向约束」的形式间接注入 analyst/modeler/coder**，而非以「知识卡片」形式。
- **`problems/mcm51-c/领域知识.md` 存在且内容完整**（术语/量纲表、典型模式 6 条、陷阱清单，实测 30 行+）——**知识在生产了，但没有注入通道**（brief 无该字段）。

### 判断

| 消费点 | background_knowledge 缺失的影响 | 靠什么补 | 结论 |
|---|---|---|---|
| analyst 建模方向 | 缺「领域常识/因果链」显式块 | reference_direction（方法族）+ per_question_direction（内嵌知识）+ problem background + 领域知识.md（未注入） | **部分补齐，机制解释缺** |
| blueprint_critic | 同上 | 同上（同看 render_full_brief） | 同上 |
| modeler / coder / model_critic | 本就不收 reference_direction，领域知识只经 direction/formula_notes/red_lines 间接到 | 上游 analyst 转述 | 无新增损失，深度依赖转述（推测） |
| paper_critic | 零渠道（连 brief 都不收） | 无 | 领域性错误可能漏判（推测） |
| 文献引用（writer references 章节） | 不依赖 brief | Semantic Scholar + 静态库 | **不受影响** |

---

## 3. 校验范围：WARN / 阻断全景

### 3.1 严格校验路径：`load_brief`（`brief.py:150-159`）

pydantic `model_validate`（**实测**验证了边界行为）：

| 校验项 | 位置 | 类型 | 行为 |
|---|---|---|---|
| JSON 不可解析 / 非 UTF-8 | `brief.py:153-155` | **硬阻断** | ValueError → CLI 报 `--brief` BadParameter（exit 2）或 check `[FAIL]`（exit 1） |
| `schema_version != 1` | `brief.py:108-112` | **硬阻断** | 同上 |
| 条目缺必填字段（direction/note/prohibition/figure/topic…）或类型错 | pydantic | **硬阻断** | 实测 `per_question_direction:[{id:'a'}]` → 报 `Field required` |
| 条目 id 重复 | `brief.py:114-119` | **硬阻断** | 实测报 `brief 条目 id 必须唯一` |
| `required_discussions.sections` 不在白名单 | `brief.py:121-132` | **硬阻断** | 白名单 9 章节（`brief.py:76-84`） |
| **extra 未知字段（含 background_knowledge/redline_rules/comparison_baselines）** | pydantic 默认 `extra='ignore'` | **静默忽略** | 实测：写入 `background_knowledge` 静默通过且被丢弃——**无 WARN 无阻断，连「字段存在但被忽略」的提示都没有** |
| 空对象 / 全空字段 | — | **静默通过** | 实测：`model_validate({})` 通过（全部有默认值） |
| 内容质量（方向是否合理等） | — | 不校验 | schema 层不评审方向（`brief.py:1-19` 定位注释） |

### 3.2 CLI 层各入口

| 入口 | 位置 | 行为 |
|---|---|---|
| `run` / `supervise` / `start` | `cli.py:328-335`（`_load_brief_or_raise`），调用点 `:2403 / :3161 / :3218` | schema 失败 → `typer.BadParameter` **硬阻断**（不跑） |
| `problem_id` 与题目宽松不匹配 | `cli.py:2176-2189`（`_warn_brief_problem_mismatch`） | **仅 [WARN]**（stderr），不阻断 |
| `brief check` | `cli.py:2229-2250` | schema 失败 → `[FAIL]` exit 1 **硬阻断**；通过后全空 → `[WARN] brief 全为空——不会注入任何约束`（不阻断） |
| `paper` 命令（evidence→paper.md 骨架） | `cli.py:1065-1078`（`_load_paper_brief`） | **宽松路径**：仅 JSON 解析 + 顶层 dict 检查，**无 schema 校验**；缺字段静默用默认值/空，无 WARN |
| `brief_coverage` 门禁 | `routing.py:14-32`（`after_blueprint_critic`） | 非 schema 校验：brief 条目未在 blueprint.brief_coverage 逐条回应 → retry；迭代超上限 → `stop` **硬阻断**（延迟式）。无 brief 恒通过 |

### 3.3 生成端（`brief_dialogue.py`）严格度

- `FIELD_SPECS`（`brief_dialogue.py:24-33`）= **8 个内容字段，无 background_knowledge**——生成端根本不会产出该字段。
- **无必填字段**：`assemble_brief`（`brief_dialogue.py:158-173`）恒输出全部 8 字段（空数组也可）；`draft_field` 失败返回 None「由调用方决定重试/跳过」（`brief_dialogue.py:88-96`）。
- `_FIELD_ID_SUFFIX`（`brief_dialogue.py:62-70`）7 个字段做 id 自动补全；reference_direction 是 `list[str]` 不做 id 补全。

### 3.4 门禁盲区（重要）

- `_BRIEF_ITEM_FIELDS`（`brief.py:87-92`）= 7 个条目型字段，**不含 `reference_direction`**（list[str] 无 id）→ **brief_coverage 门禁不覆盖文献方向**；reference_direction 即使写了 8 条，也没有「analyst 必须回应」的确定性校验。

### 3.5 校验范围总表

| 层级 | 硬阻断（exit≠0 / 不跑） | 仅 WARN | 静默通过 |
|---|---|---|---|
| schema | JSON 坏、version≠1、必填字段缺/类型错、id 重复、sections 超白名单 | — | **extra 字段丢弃**（background_knowledge 等）、空 brief、空字段、内容质量 |
| CLI run/supervise/start | schema 失败（BadParameter） | problem_id 不匹配 | — |
| brief check | schema 失败（[FAIL] exit 1） | 全空 brief | — |
| paper 命令 | —（仅 JSON 可解析性） | 无 | **schema 不校验** |
| 门禁 | brief_coverage 未回应（预算耗尽 stop） | — | reference_direction（无 id 不覆盖） |

**结论**：missing 字段（background_knowledge）**永远不会阻断**——schema 里没有它，pydantic 对缺失字段一律默认值、对多余字段一律静默忽略；`brief check` 唯一能 WARN 的是「全空」。校验体系对「字段没写」只有一种态度：**它不存在**。

---

## 4. 影响面分级结论

**总判定：background_knowledge 缺失不是「校验缺口」，而是「契约字段 + 注入点双重未落地」；实际损失被 reference_direction + per_question_direction 内嵌知识 + problem background 部分对冲，但「领域因果链/机制」的显式注入通道确实不存在。**

| 级别 | 消费点 | 影响 | 证据链 | 性质 |
|---|---|---|---|---|
| **高** | analyst 建模方向 / blueprint_critic | 缺「领域常识+因果链」显式块；`领域知识.md` 生产了但无注入通道（brief 无字段）；补位仅「方法族关键词+方向约束」层面 | 实证：`brief.py:256-258` 唯一渲染点；`prompts/analyst.py:87-88`、`prompts/blueprint_critic.py:33-34`；mcm51-c 12 字段实测；`领域知识.md` 存在但 grep 无引用 | 实证 |
| **中** | modeler / coder / model_critic | 本就不收 reference_direction；领域知识只经 direction/formula_notes/red_lines 间接达（`brief.py:289/316/343`）；无「新增」损失，但建模决策遇到 direction 未覆盖的领域分支时无兜底 | 实证（渲染器字段范围）；「无兜底」为**推测** | 实证+推测 |
| **低** | writer 参考文献章节 | **不受影响**——`select_references` 独立于 brief（`nodes/writer.py:385-389`）；但 `reference_direction` 也不达 writer，brief 的文献方向对参考文献章节零影响（推测其本意是指导文献，则属未消费） | 实证（调用链）；「本意」为推测 | 实证+推测 |
| **低但风险点** | paper_critic | 不收 brief 任何字段（`nodes/paper_critic.py:117-126` 实参实证）→ 无领域知识、无评分细则（已知死路径）、无文献对照；「评审专业性/领域性错误漏判」为**推测**（评审靠模型预训练知识兜底） | 实证（调用实参）；漏判风险为**推测** | 实证+推测 |
| **无** | brief_coverage 门禁 | background_knowledge 无 id 型条目，不参与门禁；即使未来加了字段，7 字段清单（`brief.py:87-92`）也要同步扩 | 实证 | 实证 |

**证据链完整度**：除 4 处明确标注的推测外，全部结论有 文件:行号 实证 + 运行时实测（pydantic 边界行为、mcm51-c brief 字段计数、rag.sqlite 不存在、RAG_ENABLED 默认 0）。

**关联已知项**（本报告不展开）：`redline_rules` / `comparison_baselines` 同属「契约写了、schema 未落地」（`docs/brief-playbook.md:315` 注明 comparison_baselines「字段暂不进 schema v2」）；mcm51-c 的 13 条 red_lines 以文本形式存在，机器可读 redline_rules 未落地（对应待查项）。

---

## 附：关键证据速查（文件:行号）

- 契约出处：`docs/实现计划-8-20/00-新题上线流程设计.md:26,36`；`docs/内外全流程总纲.md:103`；`docs/实现计划-8-20/8-27-操作面契约.md:162,195`；`docs/brief-playbook.md:6,13,59,315`；`docs/8-27-完整图景/05-题目档案.md:21`
- schema（12 字段、无三字段）：`src/math_agent/brief.py:94-106`
- 门禁字段清单（7 字段、无 reference_direction）：`src/math_agent/brief.py:87-92`
- reference_direction 唯一渲染点：`src/math_agent/brief.py:256-258`
- 注入点：`prompts/analyst.py:87-88`、`prompts/blueprint_critic.py:33-34`、`prompts/modeler.py:60-61`、`prompts/coder_figure_one.py:145-146`、`prompts/model_critic.py:69-71`、`prompts/writer_section.py:369-370`
- 校验：`brief.py:150-159`；CLI `cli.py:328-335 / 2176-2189 / 2229-2250 / 1065-1078 / 2403 / 3161 / 3218`；门禁 `routing.py:14-32`
- 生成端：`brief_dialogue.py:24-33 / 88-96 / 158-173`
- RAG：`config.py:100-108`（默认关）、`nodes/analyst.py:7-30`、`nodes/writer.py:37,396`
- 文献通道：`nodes/writer.py:385-389`、`tools/references.py:14`、`tools/scholar.py:21`
- paper_critic 实参：`nodes/paper_critic.py:117-126`
- mcm51-c：`problems/mcm51-c/brief.json`（12 字段、reference_direction 8 条）、`problems/mcm51-c/领域知识.md`（存在、未注入）
