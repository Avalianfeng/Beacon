# 93 · 从 brief 到 writer 稿：全链路数据流总结（cumcm23-c）

> 定稿 · 2026-09-04 · **以本题实操为准**  
> 范围：自 **brief 生成**起，到 `runs/cumcm23-c-writer-bridge-full/paper.md` 止。  
> 前置探索（S0–S2 / Diff / 研究会话算数）只作入口交代，细节见定稿 01–10。  
> 目的：讲清**每一步谁干活、数据从哪来到哪去、Beacon 内部哪个模块被调用**。

---

## 0. 一张总图

```text
┌─ 题根研究资产（已先算完，本总结不从零展开）─────────────────────┐
│  研究/scripts/*.py → 研究/data/*.csv|json + figures              │
│  解题说明.md / brief草稿 → 压缩成 brief.json                       │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
① brief 定稿          brief.json + brief check
                                ▼
② S4 预检             run --dry-run → preflight.json
                                ▼
③ S5 证据登记         _entry 读研究/data → reference add/run
                      → evidence.json → verify → recertify
                                ▼
④ S6 机械装配         tables.json → tables/；evidence+brief → paper.md 骨架
                                ▼
⑤ 写作分叉（本题都发生了）
   ├─ 5a expand（失败）     reference expand → 增量数字红线 ×2
   ├─ 5b 轨 B 应急          evidence.md + 会话写 → paper-prose.md（未溯源 0）
   └─ 5c writer 接桥实验    适配 state → writer_node → section×7
                              → writer-bridge-full/paper.md（未溯源 21）
                                ▼
⑥ 机械评审            review-check（骨架诊断 / prose 正式）
                                ▼
⑦ S8                  人批完整初稿（未做；禁批骨架）
```

**原则（D-028 / D-029）**：本地编码服务体系；写作目标形态是 **evidence → writer 链**；会话轨 B 是应急；expand 是可选填槽。

---

## 1. 入口：brief 从哪来

### 1.1 本题顺序（学-20 / 学-21）

正式顺序**不是**「先 brief 再求解」，而是：

1. Diff + 长研究会话把题算明白（定稿 10）  
2. 产物落在题根：`研究/data/`、`解题说明.md`、`经验与坑.md`、曾有 `brief草稿.md`  
3. **再压缩**成机器可读 `problems/cumcm23-c/brief.json`（定稿 11）

### 1.2 brief 里装什么（谁消费）

| 字段族 | 本题用途 | 谁读 |
|---|---|---|
| `per_question_direction` | 各问方向一句话 | `reference paper` 骨架各问摘要；writer 经 brief 切片 |
| `formula_notes` | BLEND / q=d/(1−λ) / 毛利筛选等 | 预检与文档；流水线 modeler/coder 切片（本题未跑） |
| `required_discussions` | 假设、为何 BLEND、表交付等 | 骨架「模型假设」节；writer_section 按组注入 |
| `red_lines` / `redline_rules` | 禁三年均值、禁行级弹性进定价等 | `review-check` → check_redlines / claims（D-022） |
| `figure_plan` / `scoring_notes` / `data_notes` | 图与评分关键词 | S7 claims WARN（本题 prose 未嵌图故多 WARN） |

### 1.3 内部命令

```text
math-agent brief check --brief problems/cumcm23-c/brief.json
```

- 模块：`math_agent.brief.load_brief` / schema v2  
- 本题：check OK；人闸对「去高瓜 28」按指示视为过  

**数据流**：`解题说明` + 研究表中的**已验证方向** → 人/研究者写入 `brief.json` → 磁盘；**尚未**进入 LangGraph state。

---

## 2. S4 预检：能不能开登记

```text
math-agent run --dry-run --problem problems/cumcm23-c/problem.json
  → runs/cumcm23-c-preflight/preflight.json
```

| 查什么 | 本题 |
|---|---|
| brief / 附件路径 / 基本可跑性 | `ok`，`blockers=[]` |
| WARN | 缺 sklearn 等（入口不用，可忽略） |

**内部**：CLI dry-run 路径；**不调 LLM**；不改研究数字。  
**数据流**：只读 `problem.json` + brief + source 清单 → 写出 preflight。

---

## 3. S5 证据登记：研究数字如何进入 Beacon

这是「本地编码接入体系」的核心桥（走查第 3 站的 frozen_asset 同源思想）。

### 3.1 研究侧（体系外已完成）

| 脚本 | 写出 |
|---|---|
| `研究/scripts/01_q2_demand_backtest.py` | `Q2回测_摘要.json`、误差汇总、图 |
| `研究/scripts/02_q2q3_plan.py` | `Q2Q3_摘要.json`、周汇总、补货定价、Q3 方案等 |

这些文件是**科学度事实源**。Beacon **不重算附件 2 流水**。

### 3.2 适配入口 `_entry.py`

路径演进：

1. 题根 `研究/beacon_ref/_entry.py`（开发）  
2. `reference add` 拷到 `problems/cumcm23-c/source/reference/_entry.py` 并 sha256 冻结  

行为：

```text
globals["data_dir"] = <绝对 …/source>
  → 题根 = data_dir.parent
  → 读 研究/data/*.json|csv
  → print Q1..Q4 行 + RESULT 行
```

要点：`reference run` 的 exec **不传 `__file__`**，必须用 `data_dir`（本题踩过坑并修过）。

### 3.3 命令链与产物

```text
reference add  → source/reference/ + reference.json + problem.json 哈希
reference run  → runs/cumcm23-c-reference/evidence.json
reference verify → evidence-package.json（题根）
reference recertify --verdict pass → independent-review.json
```

`evidence.json` 结构（本题）：

```text
result.ours: blend_mae, q2_week_*, q3_*
q_lines: ["Q1: …", "Q2: …", "Q3: …", "Q4: …", "RESULT: …"]
```

**数据流**：

```text
研究/data（CSV/JSON）
  --读--> _entry.py（纯 Python）
  --stdout Q/RESULT--> reference run 解析器
  --写--> evidence.json
  --校验--> evidence-package / recertify
```

**内部模块**：`math_agent` CLI `reference_*`；哈希冻结（T-19 / D-008 同类机制）。**无 LLM。**

---

## 4. S6 机械装配：骨架从哪来

### 4.1 表

```text
problems/cumcm23-c/tables.json   （题级声明：field 必须是列表）
reference tables --evidence …/evidence.json
  → runs/cumcm23-c-reference/tables/q2-mae|q2-week|q3-scheme.{md,csv}
```

数据：只取 evidence 里已有字段（如 MAE 三法、周补货/收益、Q3 n/qty/profit）。

### 4.2 骨架论文

```text
reference paper --evidence … --brief problems/cumcm23-c/brief.json
  → runs/cumcm23-c-reference/paper.md
```

| 节 | 内容来源 |
|---|---|
| 摘要 / 各问 Q 行 | evidence `q_lines` / `result.ours`（机械倾倒，可读性差） |
| 问题重述 | `problem.json` questions |
| 模型假设 | brief `required_discussions`（disc-assumptions） |
| 各问「方向」 | brief `per_question_direction` 首句 |
| 分析 prose | **【待展开】** 占位 |
| 交付表 | 与 tables 同源 |
| 附录 A/B | 溯源约定 + `_entry` sha256 |

**内部**：纯代码装配（`cli` reference paper）；**无 LLM**。  
**stage**：磁盘上有 `paper.md` → 机械 S6 完成——**≠ 论文写完**（D-028）。

---

## 5. 写作层三条路（本题都摸过）

### 5.1 expand（失败）

```text
reference expand → paper_expand.py
  输入：骨架 + evidence 白名单字符串 + brief 摘录
  行为：逐槽填【待展开】；写后增量数字红线
  本题：两次 FAIL（派生数 / 负号截断等）
```

**内部**：`math_agent.paper_expand`；LLM 填槽；**不是** graph writer 节点。

### 5.2 轨 B 应急（数字纪律最好）

```text
人工/主会话：
  ① 写 runs/…/data/evidence.md   （数字→含义→文件）
  ② 分节写 paper-prose.md        （会话 LLM，非 graph）
  ③ check_paper_numbers → 未溯源 0
  ④ review-check → review-report-prose.json
```

**数据流**：`解题说明` + evidence.json + 研究/data + Diff 摘要 → 人控写作 → prose。  
**地位（D-029）**：验证协议 + 应急；**不是**写作层终态产品。

### 5.3 writer 接桥实验（到本文终点）

脚本：`scripts/exp_writer_bridge_cumcm23c.py`  
产物：`runs/cumcm23-c-writer-bridge-full/paper.md`

详见下一节。

---

## 6. 终点放大：evidence → MathModelingState → writer → paper.md

### 6.1 适配器构造了什么 state

实验**不跑** analyst / modeler / coder / sensitivity 节点；手工填 `MathModelingState`：

| state 字段 | 本题填充来源 |
|---|---|
| `problem` | `problems/cumcm23-c/problem.md` 全文 |
| `brief` | `load_brief(brief.json)` |
| `assumptions` | 按 brief/解题说明写的 4 条 Assumption |
| `model_versions[0]` | 手工 ModelVersion（BLEND 公式、变量、验证映射） |
| `problem_blueprint` | 四问 SubQuestionBlueprint |
| `code_artifacts[0].stdout` | **evidence.json 的 q_lines + RESULT**，再附上 evidence.md 正文切片 |
| `sensitivity_runs` | 加成 P25/50/75、成本 ±20%（来自 Q2Q3_摘要 / evidence） |
| `output_dir` | `runs/cumcm23-c-writer-bridge-full/` |
| `allow_coder_llm` | False |

**关键数据通道**：writer 的「可引用数值清单」`_extract_available_numbers` **主要从** `code_artifacts.stdout` 里抽 `RESULT:` / `Q:` 行（约前 40 行），再加 `sensitivity_runs`。  
因此接桥能否守住主锚，取决于 **Q/RESULT 是否进 stdout**；evidence.md 目前多半只当附录，**未成为一等白名单**——这是 21 个未溯源的根因之一。

### 6.2 内部调用链（真 LLM）

```text
writer_node(state)                    # nodes/writer.py
  → build_outline_prompt              # prompts/writer_section.py
  → complete(..., WriterOutline)      # llm.complete，MODEL_ROUTING["writer"]
  → 写入 writer_outline_dump
  → writer_section_queue = 7 组名

loop:
  writer_section_node(state)
    → build_section_prompt(group, …)  # 注入 brief 切片 + available_numbers
    → complete(..., schema_for_group) # 可能再 repair 一轮
    → 合并进 state.paper 对应字段
    → 弹出 queue

render_markdown(state)                # 用 templates 拼最终 md
  → paper.md
```

七组固定顺序：

`abstract_problem` → `assumptions_notation` → `model` → `solution` → `sensitivity` → `conclusion` → `references`

**未调用**：`coder_*`、`modeler`、`paper_critic`（本实验停在 render）、`latex`、`finalizer`。  
**未走**：CLI `restart --from writer`（至今只支持 `--from coder`）——用的是**脚本直调节点**，等价于接桥烟测，不是正式操作面命令。

### 6.3 数据在 writer 里怎么被用

```text
brief.json
  └─ render_slice(..., "writer_section", group_name)
       → 各节 prompt 末尾「讨论点」

code_artifacts.stdout（Q/RESULT）
  └─ _extract_available_numbers
       → 「只能用以下数值」硬约束块

model_versions / assumptions / blueprint
  └─ 大纲与模型/假设节的结构素材

sensitivity_runs
  └─ sensitivity 节 + available_numbers 中的 [sensitivity] 行

problem.md
  └─ 问题重述素材（render 时也可能把题面顶进标题区——本题稿有题面污染标题的现象）
```

### 6.4 写出后的闸门

```text
check_paper_numbers --paper …/writer-bridge-full/paper.md --evidence <一堆>
  → 主锚命中；21 未溯源（派生%、截断小数、文献年、假种子 42）
```

对照：`paper-prose.md` 同套证据下 **未溯源 0**。

---

## 7. 分阶段「内部用了什么」速查表

| 阶段 | 外部/本地 | Beacon 内部 | LLM? |
|---|---|---|---|
| brief 定稿 | 研究者写 json | `brief` schema / `brief check` | 否（本题直写） |
| S4 | — | `run --dry-run` | 否 |
| S5 | `_entry` 读研究/data | `reference add/run/verify/recertify` | 否 |
| S6 表/骨架 | tables.json | `reference tables/paper` | 否 |
| expand | — | `paper_expand.py` | 是（失败） |
| 轨 B prose | 会话写作 | 仅事后 `check_*` / `review-check` | 会话侧是；图内否 |
| writer 桥 | 适配脚本 | `writer_node` / `writer_section_node` / `llm.complete` / `render_markdown` | 是 |
| S7 | — | `review-check` 包一层 check_* | 否（机械） |
| S8 | 人 | `accept` | 否（未做） |

---

## 8. 磁盘上的「同一条数字」如何搬家（举例）

以 **BLEND MAE = 12.9643** 为例：

```text
01_q2_demand_backtest.py
  → 研究/data/Q2回测_摘要.json["合计MAE"]["BLEND"]
  → _entry 读入，打印进 Q2/RESULT 行
  → evidence.json result.ours.blend_mae / q_lines
  → reference paper 骨架摘要（机械粘贴）
  → evidence.md 语义行（轨 B）
  → paper-prose.md（人控引用）
  → state.code_artifacts.stdout（接桥）
  → writer available_numbers
  → writer-bridge-full/paper.md 摘要/模型/求解节
```

以 **Q3 n=28 / profit=794.6371** 同理，源头是 `02_q2q3_plan.py` → 摘要/主方案 csv → `_entry` → evidence → 各写作路径。

**禁止路径**：手改 `研究/data` 数字却不重跑 `_entry`/verify；或在论文里写白名单外派生数却声称「代码输出」。

---

## 9. 两条论文产物如何选用（本题现状）

| 文件 | 路径 | 用途建议 |
|---|---|---|
| 骨架 | `runs/cumcm23-c-reference/paper.md` | stage / 机械溯源；**不可批** |
| 轨 B 初稿 | `runs/cumcm23-c-reference/paper-prose.md` | **人评优先**（未溯源 0） |
| writer 实验稿 | `runs/cumcm23-c-writer-bridge-full/paper.md` | 证明体系写作段可接；需严闸后才可进人评 |

S7：`review-report.json`（骨架诊断）vs `review-report-prose.json`（prose）。  
S8：若批，须 `--paper …/paper-prose.md`（或将来过严闸的 writer 稿），**禁止**批骨架。

---

## 10. 和「为体系服务」差在哪（诚实缺口）

已通：

- 研究数字 → evidence 冻结链  
- 骨架装配  
- 脚本级 **writer 起跑**（本总结终点）

未产品化：

- `restart --from writer`（CLI 仍只支持 coder）  
- evidence.md 作为 writer **一等白名单**  
- 写后 `--strict` 作为 S6 写作完成判据  
- paper_critic 环接在适配器之后  

因此：**数据已经能为体系服务到 evidence；写作段刚用实验脚本接上，还不是操作面正式一棒。**

---

## 11. 相关文件索引

| 角色 | 路径 |
|---|---|
| brief | `problems/cumcm23-c/brief.json` |
| 登记入口 | `problems/cumcm23-c/source/reference/_entry.py` |
| evidence | `runs/cumcm23-c-reference/evidence.json` |
| 语义卡 | `runs/cumcm23-c-reference/data/evidence.md` |
| 骨架 | `runs/cumcm23-c-reference/paper.md` |
| 轨 B | `runs/cumcm23-c-reference/paper-prose.md` |
| writer 稿 | `runs/cumcm23-c-writer-bridge-full/paper.md` |
| 实验脚本 | `scripts/exp_writer_bridge_cumcm23c.py` |
| 决策 | D-028、D-029；学-25～27 |
| 分站 | 定稿 11–17、14附 |

---

## 更新

- 2026-09-04 建立：按 cumcm23-c 实操从 brief 总结至 writer-bridge-full/paper.md。
