# brief_coverage 门禁真实行为核查（2026-08-29）

> 背景：`全流程分析/brief真实调用检查.md` 待查项「brief_coverage 门禁（blueprint_critic 后）与 40 条逐条覆盖的真实行为」。
> 方法：只读代码核查 + `runs/` 全部含 brief 的真实 run 产物取证（steps/、checkpoints.sqlite、final_state.json、state_summary.json、progress.jsonl、supervisor.log、trace.json）。

---

## 0. 结论速览

1. **mcm51-c brief 实际 51 条带 id 条目，不是 40 条**。「40 条」是三处错误的叠加：①mcm51-a 的 brief 恰为 40 条（口径串台）；②`insight.py:456` 的 `_jsonable` 把列表截断到前 40 项，analyst 步骤产物恰好显示 40 条（记录截断，非真实条数）；③mcm51-c brief 的 git 历史（47→51 条）从未是 40。CLI `brief check` 权威输出为 **51 条待回应条目**（cli.py:2244，已实跑验证）。
2. **门禁真实行为链**：analyst prompt 强制逐条回应 → `blueprint_critic` 评审 → `routing.after_blueprint_critic` 先跑确定性 `brief_coverage_problems`（brief.py:174）→ 有缺漏/deviation 无理由 → 重试（`MAX_BLUEPRINT_ITERATIONS=2`，config.py:53，最多一次 retry）→ 耗尽仍不满足 → **stop 硬停**；无缺漏且 critic approved → advance。
3. **真实产物**：4 个带 brief 的真实 run 全部实际全量覆盖（refA 51/51、mcm51-b 52/52、mathorcup16 25/24 多 1 条幻觉 id、51mcm-a 39/40 因运行时用了门禁提交前的旧代码而漏检）。**deviated 路径从未被真实使用**（169 条回应全部 followed）；门禁的 retry/stop 路径也从未在真实 run 中触发过。

---

## 1. 条目数核实：51 ≠ 40

### 1.1 brief.json 逐字段统计（python 实跑，只读）

| 字段 | 条目数 | 带 id 数 | 说明 |
|---|---:|---:|---|
| per_question_direction | 6 | 6 | |
| formula_notes | 5 | 5 | |
| required_discussions | 9 | 9 | |
| red_lines | 13 | 13 | |
| figure_plan | 5 | 5 | |
| scoring_notes | 4 | 4 | |
| data_notes | 9 | 9 | |
| **七字段合计** | **51** | **51** | 与 `_BRIEF_ITEM_FIELDS` 口径一致 |
| reference_direction | 8 | 0 | 纯字符串列表，无 id，不参与门禁 |

与 `src/math_agent/brief.py:41-47` 的 `_BRIEF_ITEM_FIELDS`（七字段）逐一对照：**完全一致，51 条全部进 `brief_item_ids`（brief.py:165-171）**，即门禁按这 51 个 id 校验。题面给的口径没有数错，51 是准确的。

### 1.2 CLI 权威输出（实跑验证）

```
$ python -m math_agent.cli brief check --brief problems/mcm51-c/brief.json
[OK] problems\mcm51-c\brief.json 通过校验（schema_version=1）
  - per_question_direction（逐题方向）：6 条
  ...
  - reference_direction（文献方向）：8 条
共 51 条待回应条目（brief_coverage 门禁按这些 id 校验）   ← cli.py:2244
```

### 1.3 「40 条」的三个来源，全部不成立

1. **mcm51-a 才是 40 条**：`problems/mcm51-a/brief.json` = 40 条带 id 条目（2026-08-18 创建，git commit 7bb3bfc 提交信息「M6 brief 1.2-reg-coef(40条)」即指 mcm51-a）。文档把 mcm51-a 的口径安到了 mcm51-c 头上。
2. **产物记录截断**：`src/math_agent/insight.py:456` `_jsonable` 对列表取前 40 项（dict 取前 80 键，454 行）。mcm51-c-refA 的 analyst 步骤产物（steps/0001、0002）因此显示 40 条 —— 但同 run 的 `checkpoints.sqlite`（unclipped）、`final_state.json`、`state_summary.json` 均为 51 条（见 §4.2）。任何人只看 steps/ 产物就会数出「40 条」。
3. **mcm51-c brief 的 git 历史从未是 40**：1ffec94（47 条）→ 38aa1be（+formula-solver/reference/rl-greedy/rl-result-format，51 条）→ ff8a4ac（51 条）。任何版本都不是 40。

### 1.4 文档出处与差异结论

- `全流程分析/03-第2站-操作面S0-S3.md:37`「真实形态（mcm51-c 40 条）」：**错误**，应 51 条。
- `全流程分析/08-第5站-真实案例走查.md:14`「brief.json（40 条，12 字段）」：**错误**，应 51 条。
- `全流程分析/05-第2站-操作面S6-S8.md:82`「S3 brief（40 条压缩注入物）」、`子agent分析/04-…md:7`「唯一必须覆盖全 40 条的产物」、`后续行动清单.md:46`「40 条逐条覆盖」：同一口径的延续错误。
- 注：12 字段（8 内容 + schema_version/problem_id/created_at/source）是对的；reference_direction 8 条无 id 是纯文本方向，不进门禁，这一点文档口径一致。

---

## 2. 门禁完整行为链（生成 → 校验 → 重试 → 硬停）

### 2.1 生成端：analyst 的强制逐条回应要求

- `src/math_agent/prompts/analyst.py:17-20`（SYSTEM）：`"blueprint 必须通过 brief_coverage 字段逐条回应 brief 的每一个条目（status=followed 表示遵守并体现在蓝图中；status=deviated 表示偏离并必须给出理由，如与题面冲突）；与题面冲突时以题面为准并标注偏离。"` + `"brief_coverage 条目必须与 brief 条目一一对应，一条不落，不得用笼统的'总体遵守'代替。"`
- `analyst.py:61`（schema hint）：`"brief_coverage": [ # 人工建模预备逐条回应（若提供了 brief；必须与 brief 条目一一对应） {"brief_item_id": str, "status": "followed|deviated", # deviated 必须给出非空 reason, "reason": str}]`
- 评审端同步要求：`src/math_agent/prompts/blueprint_critic.py:11-12`「blueprint.brief_coverage 未逐条回应 brief 条目（或回应空泛、deviated 无理由）也属于严重问题」；`blueprint_critic.py:52`「8. 若提供了 Modeling Brief：brief_coverage 是否逐条回应了 brief 条目」。
- 字段定义：`src/math_agent/state.py:135` `brief_coverage: list[BriefCoverageItem]`（BriefCoverageItem = brief_item_id + status[followed|deviated] + reason，brief.py:136-140）。

### 2.2 校验端：brief_coverage_problems（确定性，不调 LLM）

`src/math_agent/brief.py:174-195` 判定规则：
- `brief is None` → 直接通过（无 brief 不设门禁，向后兼容）；
- `blueprint is None` → 记问题「ProblemBlueprint 缺失」；
- 对 brief 每个 id（`brief_item_ids`，按七字段声明顺序）：`covered` 中找不到该 id → 记「未在 blueprint.brief_coverage 中回应」；`status=deviated` 且 reason 空白 → 记「声明偏离但未给出理由」；
- `status=followed` → 通过；`deviated+非空 reason` → 通过（显式偏离合法）。
- 只查「brief→coverage」单向缺失；**coverage 里多出的 id（幻觉）不构成问题**（§4.4 有实证）。

### 2.3 路由端：routing.after_blueprint_critic（src/math_agent/routing.py:17-41）

```
report = state.latest_critic("analyst", critic_type="blueprint")   # 无 → retry
problems = brief_coverage_problems(state.brief, state.problem_blueprint)
if problems:
    if state.blueprint_iteration >= MAX_BLUEPRINT_ITERATIONS: → stop   # 硬停
    return retry
if report.approved: → advance
if state.blueprint_iteration >= MAX_BLUEPRINT_ITERATIONS: → advance_with_warning
→ retry
```

- `MAX_BLUEPRINT_ITERATIONS = 2`（src/math_agent/config.py:53，blueprint critic 允许首次 + 一次 retry）。
- 语义：blueprint_critic_node 返回时 `blueprint_iteration` 已递增；首次审查 iteration=1，门禁未过 → retry（1 次机会）；第二次审查 iteration=2 仍未过 → **stop 硬停**（人工输入方向不能被忽略）。
- **门禁先于 approved 判断**：即使 critic 打 approved，只要 brief_coverage 有缺漏也照样 retry/stop —— 门禁是防忽略人工输入的兜底，不依赖 LLM 评审。
- 单测覆盖：`tests/test_routing.py:234`（缺口<上限→retry）、`:250`（缺口=上限→stop）、`:265`（全 covered+approved→advance）；`tests/test_brief.py:125/132/142`（缺失/deviated 无理由/followed+deviated 有理由）；`tests/test_graph_gate.py:78`（图级全 followed→放行、只审一次）。

### 2.4 门禁重试时的一个观察（附带发现）

gate 触发的 retry 走 analyst 节点，但 analyst 只注入 critic 反馈当且仅当 critic 未通过（`src/math_agent/nodes/analyst.py:42-44`：approved 的 critic 反馈会被置 None）。即**门禁缺口触发的 retry，analyst 收不到「缺了哪些 id」的定向反馈**，只能靠重新注入的完整 brief 自行补齐。门禁回路存在但缺少「定向修单」信息通道（当前无真实 run 触发过该路径，影响未实测）。

---

## 3. CLI 面

- `src/math_agent/cli.py:2227-2244` `math-agent brief check`：校验 brief schema 后按 `FIELD_SPECS` 逐字段打印条数，再打印「共 N 条待回应条目（brief_coverage 门禁按这些 id 校验）」。**数的是 `brief_item_ids(brief)`**（cli.py:2241 调用），即七字段 id 总数 = 51（mcm51-c）。纯校验，不调 LLM。
- `cli.py:2360` `run --dry-run` 预检同样打印「（N 条待回应条目）」，同一口径。
- 其余相关：`cli.py:2222-2226` 提示「填写后运行 brief check 校验；建议沉淀到 problems/<题号>/brief.json」。

---

## 4. 真实产物核查（runs/ 全量扫描）

搜索范围：`problems/mcm51-c/`（无 brief_coverage 产物，仅 brief.json 输入）、`runs/*/steps/*_analyst_*/output.json`（4 个 run 命中）、各 run 的 `checkpoints.sqlite` / `final_state.json` / `state_summary.json` / `progress.jsonl` / `supervisor.log` / `trace.json`。`problems/mcm51-c/` 下没有 blueprint 产物（blueprint 只在 runs/ 里）。

### 4.1 全景表（全部 4 个带 brief 的真实 run）

| run | brief 条目 | analyst 原始输出 | 门禁结果 | 证据 |
|---|---|---|---|---|
| `runs/51mcm-a-brief-v1`（8-18） | **40**（mcm51-a） | 39/40，**缺 `1.2-reg-coef`** | **漏检**（运行时是门禁提交前的旧代码，见 4.3） | steps/0001、checkpoints.sqlite（39）、final_state.json（39）、supervisor.log 23:40 起跑 |
| `runs/mcm51-b-brief-v1`（8-21） | 52 | 52/52 全 followed | 通过（0 problems，无 retry） | 原始 content 52 个 id；final_state.json coverage=52 |
| `runs/mcm51-c-refA`（8-26） | **51** | **51/51** 全 followed（原始 content 含全部 51 个 id） | 通过（0 problems，单轮 analyst+critic 即 advance） | steps/0001 content、checkpoints.sqlite（51）、final_state.json（51）、progress.jsonl 单轮 |
| `runs/mathorcup16-c-p3-s9`（8-27） | 24 | 25 条（**多 1 条幻觉 id「参考文献方向」**，无缺漏） | 通过（门禁不查多余 id） | checkpoints.sqlite（25）、progress.jsonl 单轮 |

### 4.2 mcm51-c-refA 细节：51 条全量覆盖，steps 显示 40 是记录截断

- analyst 原始 LLM 响应（steps/0001 `content`，18061 字符）内 `brief_item_id` 出现 **51 次**，最后一条是 `data-q3-timeseg`（「附件3无时间列，跨集预测假设声明。」）——模型确实逐条回应了全部 51 条，且都带实质 reason。
- 同一文件的 `parsed` 字段只有 40 条 —— 因为 `record_llm_result` 走 `_jsonable`（insight.py:456 `list(value)[:40]`）截断。steps/0002（node 步）同样截断为 40。
- 未截断的真值：`runs/mcm51-c-refA/checkpoints.sqlite`（msgpack 解码 problem_blueprint.brief_coverage = 51 条，全 followed，含 data-* 9 条与 score-q2/q5-warning）、`final_state.json`（51 条）、`state_summary.json`。
- 状态分布：51/51 全 `followed`，0 deviated；`blueprint_iteration=1`（只审一次即 advance），progress.jsonl 证实 analyst/blueprint_critic 各只跑一轮，无 retry。
- **门禁在 refA 上无可拦之缺**——LLM 表现好于文档宣称的「40 条」。

### 4.3 51mcm-a-brief-v1：唯一一次真实覆盖缺口，因代码版本漏检

- 39/40，缺 `1.2-reg-coef`（data_notes 字段）。用当前代码对同状态实跑 `brief_coverage_problems` → 1 个 problem（会 retry），但真实 run 单轮通过、无 retry。
- 时间线：门禁 commit `3e97a20`（8-18 23:39）vs supervisor worker 起跑 23:40:04。CLI 进程（模块导入早于 commit）执行的仍是**门禁提交前版本的 routing.py**。这是「门禁从未在真实覆盖缺口上拦过一次」的唯一实证缺口，属于**上线时序事故**，不是门禁逻辑缺陷；其后 3 个 run 均在门禁代码下运行且全部全量覆盖，无触发机会。

### 4.4 mathorcup16-c-p3-s9：幻觉 id 不被门禁拦截

- brief 24 条，LLM 输出 25 条：24 条全部命中 + 1 条多余 id「参考文献方向」（疑似从 reference_direction 文本误生成）。`brief_coverage_problems` 只做 brief→coverage 方向的存在性检查，多余 id 不构成问题 → 通过。方向性检查的固有盲区（对「model 多回应了不存在的条目」无感），当前无实害。

### 4.5 deviated 路径是否被真实使用过：**没有**

- 4 个 run 共 167 条门禁条目回应（39+52+51+25），**全部 `followed`，0 条 `deviated`**（全局 grep 所有 analyst 产物无 deviated 记录）。
- deviated+reason 的合法路径只在单测里被覆盖（tests/test_brief.py:142），真实流水线从未走通过。
- 门禁的 retry/stop 分支同样从未在真实 run 触发（4.1 表）。

---

## 5. 最终结论

1. **门禁真实行为链**（代码 + 单测 + 4 次真实 run 交叉验证）：
   `analyst prompt 强制逐条回应（analyst.py:17-20）→ blueprint_critic 评审（含 brief_coverage 检查项，blueprint_critic.py:11-12/52）→ routing.after_blueprint_critic 先跑确定性 brief_coverage_problems（routing.py:29-36，brief.py:174-195）→ 有缺漏 → retry（iteration<2）/ stop 硬停（iteration≥2，config.py:53）→ 无缺漏且 approved → advance`。生成→校验→重试→硬停全链成立。
2. **40 vs 51**：mcm51-c brief 实为 **51 条**；「40 条」= mcm51-a 口径串台 + `_jsonable` 列表截断（insight.py:456）制造的表象 + 文档沿抄。CLI 权威值 51（cli.py:2244）。建议全流程分析各文档统一改为 51（或按题引用各自 brief 的真实条数）。
3. **deviated 路径**：真实产物中 0 使用；重试/硬停分支从未被真实触发。唯一一次真实覆盖缺口（51mcm-a 39/40）因运行时代码早于门禁提交而漏检——门禁上线后尚未经历真正的失败演练。
4. **附带发现**（建议后续关注）：
   - `insight.py` `_jsonable` 的 `[:40]` 列表截断会污染步骤产物的可审计性（refA steps 显示 40 vs 真值 51；凡列表 >40 项的字段都受影响，不止 brief_coverage）；
   - 门禁 retry 无「缺哪些 id」定向反馈通道（analyst.py:42-44 只透传未通过 critic 的反馈）；
   - 门禁不查 coverage 多余 id（幻觉条目不拦截）。
