<!-- 红线机器化落地检查 · 2026-08-29 · 只读探查（不改任何代码/数据） -->

# 02 · redline_rules 机器可读红线落地检查

> **结论速览**：`redline_rules` 是一个**只存在于文档层、从未进入代码层**的契约字段。
> 设计文档（M3 机制工程）给出完整 schema，但执行决策是「已拍板不排期 / 暂缓」；
> brief schema 代码只支持 `schema_version=1`，且 pydantic 对未知字段**静默丢弃**（连警告都没有）；
> 13 条文本红线里约 **7 条可直接机器化**、5 条部分可机器化、1 条基本只能靠 LLM。
> 现网没有任何确定性工具结构消费 `red_lines`（唯一「读 brief」的 check_l4_gates 也只是全文拼进扫描语料，且操作面包装层 ops_review 根本没传 `--brief`）。

---

## 一、契约写了什么：`redline_rules` 的文档出处（文件:行号 + 原文）

| # | 出处 | 行号 | 原文（关键句） |
|---|---|---|---|
| 1 | `docs/archive/8-20执行批次/02-批次1-机制工程A-M3红线确定性校验.md` | 6 | 「v2 调整（2026-08-21）：schema v2 合并范围 = spec v2 + `background_knowledge` + `redline_rules`」 |
| 2 | 同上 | 18 | JSONC 示例：`"redline_rules": [ {"id":"rl-001", "target":"code\|stdout\|paper", "rule_type":"literal_ban\|expr_ban\|symbol_ban\|result_rule", "pattern":"600.71", "severity":"hard", "note":"禁止硬编码官方参考值"} ]` |
| 3 | 同上 | 24–29 | rule_type 语义：`literal_ban`（数值字面量）/ `unit_mix_ban`（单位混用，D3 决策并入 M5 校验层）/ `expr_ban`（正则）/ `symbol_ban`（符号名出现检测，宁严勿松）/ `result_rule`（stdout 数值等式/区间） |
| 4 | 同上 | 37 | 「兼容：无 brief / 无 `redline_rules` → 恒通过（向后兼容，同 brief_coverage 语义）；`brief check` 校验规则 schema 合法性」 |
| 5 | 同上 | 42–43 | 设计接入：`src/math_agent/brief.py` 新增纯函数 `redline_violations(brief, code_artifacts, stdout_lines)`；接入 `routing.py:115 after_model_code_consistency` 前 |
| 6 | `docs/实现计划-8-20/8-26-M3红线机器化说明.md` | 8–12 | 「M3 = 把 brief 里的『红线/禁止项』从文本变成机器可读规则，在代码/输出产物上做确定性校验，违反即进入 修复→停止 路径——不再靠 LLM 评审『自觉』压线放行」 |
| 7 | 同上 | 25–26 | 历史实证：B16（brief-v1 中 K_avg=0.1783 违反禁整体 K 红线，LLM 评审仍给 8 分压线放行） |
| 8 | 同上 | 76–80 | 取舍建议：选项 1 最小版（只 literal_ban+expr_ban+result_rule warn）≈0.5–1 天；选项 2 暂缓；「结论：M3 **不是全流程阻塞项**」 |
| 9 | `docs/brief-playbook.md` | 13 | 「产出物 = `problems/<题号>/brief.json`（八字段 + `background_knowledge` + `redline_rules`，注入流水线）」 |
| 10 | 同上 | 293 | 「风险与口径红线 → `red_lines` + 机器可读 `redline_rules`（M3 批次 1 落地前先存文本）」 |
| 11 | 同上 | 310 | 字段映射表：`red_lines` 行「同时写机器可读 `redline_rules`（M3，批次 1 落地前先存文本）」 |
| 12 | 同上 | 351 | pilot 简报模板「红线检查：<redline_rules 违规列表（M3 落地后自动，落地前人工）>」 |
| 13 | `docs/实现计划-8-20/README.md` | 70 | 「[02-批次1-机制工程A-M3红线确定性校验] … **已拍板不排期**（M3 说明见 8-26-M3红线机器化说明）· 已归档」 |
| 14 | `docs/实现计划-8-20/8-27-操作面契约.md` | 195 | 「产出：`problems/<题号>/brief.json`（八字段 + 可有 `background_knowledge` / `redline_rules`）」 |
| 15 | `docs/实现计划-8-20/00-新题上线流程设计.md` | 108 | 「spec v2 + brief `background_knowledge` + M3 `redline_rules` → **一次 schema v2 升级**（向后兼容 + 迁移脚本或直接双版本支持），排期在 M3 实现之前完成 schema 设计评审」 |
| 16 | `docs/archive/8-20执行批次/09-pilot模式与早期反证.md` | 28 | 「若 M3（红线机器化）已落地，简报附 `redline_rules` 违规检查结果；未落地前人工核对」 |

**出处结论**：有明确出处，且不止一处——设计文档（02-批次1）给出完整 schema 与校验器设计，playbook v3.1 把「同时写机器可读 redline_rules」写进字段映射表与 pilot 模板。但**没有一处契约要求当前必须已实现**：所有地方都标注「M3 批次 1 落地前先存文本」，README 明确「已拍板不排期」。契约自我降级为「文本先行、机器化待定」。

git 历史佐证：`git log -S 'redline_rules' -- src/ scripts/` 仅命中两条 **docs 提交**（9590688、21f26f5），代码目录从未出现该字段；`redline_violations` 函数名在全仓 git 历史零命中。

---

## 二、代码实际有什么：schema 侧证据

| 证据 | 文件:行号 | 内容 |
|---|---|---|
| `ModelingBrief` 字段清单 | `src/math_agent/brief.py:78–102` | 12 个字段（8 内容字段 + schema_version/problem_id/created_at/source + reference_direction），**无 redline_rules** |
| `RedLineItem` 模型 | `src/math_agent/brief.py:39–42` | 仅 `id / question_id / prohibition`（纯文本），无 pattern/rule_type/severity |
| schema 版本门禁 | `src/math_agent/brief.py:104–110` | `_check_version`：`value != 1` 直接 `raise ValueError`——**代码只认 schema_version=1，schema v2 从未实现** |
| 未知字段静默丢弃（实测） | `brief.py` ModelingBrief（pydantic 默认 extra=ignore） | 实测：给 mcm51-c brief.json 注入 `redline_rules` 键后 `ModelingBrief.model_validate` **返回 OK**、`hasattr(b,'redline_rules')=False`、`model_extra=None`。即：即使有人按 playbook 写了 `redline_rules`，`brief check` 也会打 `[OK]` 并通过，规则被**无声吞掉** |
| brief init 模板 | `src/math_agent/cli.py:2211` | 模板 payload 12 字段，无 redline_rules |
| brief check 校验范围 | `src/math_agent/cli.py:2228–2252` | 只做 load_brief 校验 + 各字段条目计数，无任何规则合法性检查（设计文档 §二 4 要求的「`brief check`：非法 rule_type / 缺 pattern 的规则报错」不存在） |

---

## 三、check 工具是否消费 red_lines：逐一核查（证据）

### 3.1 五个工具全文核查

| 工具 | 是否读 brief | 证据（文件:行号） |
|---|---|---|
| `scripts/check_paper_numbers.py`（502 行全文） | **否** | 参数仅 `--paper / --evidence / --allow / --strict / --verbose / --traceability`（build_parser，行 424–441）；全文无 red_line/brief 概念 |
| `scripts/check_assumption_claims.py`（419 行全文） | **否** | 参数仅 `--paper / --strict / --verbose`；grep 到的 "brief" 仅出现在 docstring 示例路径 `runs/mcm51-b-brief-v1/paper.md`（行 9、55），是 run 目录名，非读取 brief |
| `scripts/check_gap_trigger.py`（105 行全文） | **否** | 输入 `--json` 证据文件（sensitivity.json 等），递归扫 LB_KEYS/MS_KEYS 配对（行 14–15）；与 brief 无关 |
| `scripts/check_l4_gates.py`（158 行全文） | **名义上有 `--brief`，但只做全文拼接** | 行 111 参数定义「可选 brief.json，全文并入扫描语料」；行 137–142 `parts.append(_read_text(brief))` —— brief 原文被当**纯文本**拼进 corpus，再跑 G1–G4 正则（敏感性/重建/异常）。**不解析 JSON、不读 red_lines 字段、不消费任何红线语义**；且 brief 文本进语料可能反而造成假通过（brief 里出现「异常检测」字样会满足 G3 触发、出现「操作定义」会满足 G3 通过） |
| `src/math_agent/ops_review.py`（122 行全文） | **不传 brief** | `run_review` 调 check_l4_gates 时只传 `--paper` + `--strict`（行 47–53），**从未传 `--brief`**——即使 check_l4_gates 有能力拼 brief 文本，操作面评审主路径也不会传。其余三个 check 均无 brief 参数（行 33–45、56–63） |

**结论**：5 个工具**零个结构消费 red_lines**。check_l4_gates 的 `--brief` 是文本级拼接（还会污染语料），且实际未被 ops_review 调用方使用。

### 3.2 src/ 内 red_lines 的全部消费点（唯一执行机制 = prompt 注入 + 声称性门禁）

| 消费点 | 文件:行号 | 性质 |
|---|---|---|
| `render_full_brief` | `src/math_agent/brief.py:237–240` | 文本注入 analyst / blueprint_critic（`prompts/analyst.py:87–88`、`prompts/blueprint_critic.py:33–34`）——**LLM 自觉** |
| `render_coder_brief` | `src/math_agent/brief.py:299–302` | 文本注入 coder（`prompts/coder_figure_one.py:145–146`）「红线（违反即失败，必须避开）」——**LLM 自觉** |
| `render_critic_brief` | `src/math_agent/brief.py:322–325` | 文本注入 model_critic（`prompts/model_critic.py:69–71`）「红线（模型/推导触碰记 issue）」——**LLM 评审自觉** |
| `brief_coverage_problems` | `src/math_agent/brief.py:254–273`；路由接入 `routing.py:25–32` | 确定性门禁，但**只查「blueprint 是否逐条回应了 brief 条目 id」**（followed / deviated+理由），**不校验红线内容本身**——防忽略，不防违反 |
| state 存储 | `src/math_agent/state.py:313–314`、`133–135` | brief 对象 + brief_coverage 列表，无红线结果字段 |

全仓 `grep -rn 'red_line' --include='*.py' src/ scripts/` 命中仅上述 5 处文件（brief.py / brief_dialogue.py / cli.py / sample_brief_direction.py，后三者只是字段声明/模板/示例）。`graph.py` 无 brief 引用；设计文档 §二 1 规划的 `redline_violations` 纯函数**不存在**；gate_diagnostics 的 `redline_violations` 段**不存在**。

---

## 四、mcm51-c 实际 13 条红线逐条可机器化判定

来源：`problems/mcm51-c/brief.json`（schema_version=1，12 字段，**无 redline_rules**；red_lines 13 条，均无 question_id 或部分有）。判定基准：能否映射到设计文档已有的 rule_type（literal_ban/expr_ban/symbol_ban/unit_mix_ban/result_rule）或等价静态/产物校验，且不依赖 LLM 语义理解。

| # | id | 红线（prohibition 摘要） | 可机器化判定 | 映射形态 |
|---|---|---|---|---|
| 1 | rl-blast-nan | 禁止把爆破点距离/单段最大药量的空值当缺失插补（空值=非爆破时刻） | ✅ **可**（中） | symbol_ban/expr_ban：扫 code 中 `fillna/interpolate/impute` 作用于附件 4/5 字段 |
| 2 | rl-target-nan | 实验集表面位移 100% 空值是预测目标，禁止当缺失补齐 | ✅ **可**（中） | symbol_ban：对实验集列做 impute 的调用；需数据血缘区分训练/实验集（半自动） |
| 3 | rl-units | 单位混用禁止（mm/10min vs mm/h 等），贡献度须统一尺度 | ✅ **可**（设计已定义） | `unit_mix_ban`（设计文档 02-批次1:26；warn 级先观察误报） |
| 4 | rl-timebase | 跨附件时间基准混用禁止（五个附件起点各异） | ⚠️ **部分** | 数据校验层可断言时间戳起点/范围，但需血缘理解；现 check 体系无此维度 |
| 5 | rl-leak | 禁止随机切分做 CV，须时序前向/滚动切分 | ✅ **可**（高） | expr_ban/symbol_ban：扫 `train_test_split(...shuffle)` / `KFold(shuffle=True)` / 随机采样符号 |
| 6 | rl-stage-leak | 禁止把实验集阶段标签当训练特征 | ✅ **可**（中） | symbol_ban：特征工程代码中阶段标签列进入特征矩阵的引用 |
| 7 | rl-microseism-blast | 禁止用微震事件数代理「是否爆破」标识 | ✅ **可**（中） | symbol_ban：`is_blast` 构造代码引用 microseism 列 |
| 8 | rl-colinear | 禁止贡献度只报 Pearson（强共线须偏相关/增量R²/SHAP+VIF） | ⚠️ **部分** | result_rule + symbol_ban：stdout/代码只出现 pearson 且无 SHAP/偏相关/VIF 时触发（组合判据） |
| 9 | rl-rainfall | 禁止跨附件类比降雨量语义（43% 零 vs 98% 零各自构造特征） | ❌ **基本靠 LLM** | 语义理解（「语义不同」不可静态表达）；仅能弱扫「降雨特征是否按附件分函数构造」 |
| 10 | rl-table-format | 交付表须逐格对齐题面（表 1.1/3.1/3.2/4.1 格式） | ⚠️ **部分** | paper 目标（target=paper）：解析论文表格列名/行数比对题面规格，可半自动；「样例 abc」细节靠人 |
| 11 | rl-q1-points | 禁止把表 1.1 的 x=7.132… 当时间/索引（是附件 A 列位移取值） | ⚠️ **部分** | 数据校验：断言表中 x 值 ∈ 附件 A 列取值集合且 y 对齐 B 同刻——可写成校验脚本，但需人工把数值红线翻译成断言 |
| 12 | rl-greedy | 禁止自写贪心/启发式冒充主方案（主方案须来自 reference_solver.py） | ⚠️ **部分** | symbol_ban（greedy/heuristic 符号）+ result_rule（主方案输出与 reference_solver 输出对撞）；「冒充」意图机器难判 |
| 13 | rl-result-format | 禁止臆造 RESULT 行字段/格式（须原样透传 reference_solver） | ✅ **可**（高） | result_rule：解析 stdout RESULT 行与 reference_solver 输出做字段名/数量/顺序 schema 比对 |

**占比**：✅ 直接可机器化 **7/13 ≈ 54%**（1、2、3、5、6、7、13）；⚠️ 部分可机器化 **5/13 ≈ 38%**（4、8、10、11、12，需血缘/表 schema/人工翻译断言辅助）；❌ 基本只能 LLM 理解执行 **1/13 ≈ 8%**（9）。即：**大部分红线在技术上完全具备确定性校验条件**，且大多能映射到 2026-08-21 设计文档就已定义好的 rule_type——未落地不是技术障碍，是排期决策。

---

## 五、证据链：红线执行的完整弱保证链条

```
契约层：playbook 要求「red_lines + 机器可读 redline_rules（M3 落地前先存文本）」
         （docs/brief-playbook.md:293,310）＋ M3 设计给出完整 schema 与校验器设计
         （docs/archive/8-20执行批次/02-批次1:18-43）
    │
    ▼ 决策层：README「已拍板不排期」（docs/实现计划-8-20/README.md:70）；
            8-26 说明「不是全流程阻塞项，建议最小版或暂缓」（8-26-M3红线机器化说明.md:76-80）
    │
    ▼ 代码层：schema 无 redline_rules（brief.py:78-102）；schema_version 只支持 1（brief.py:104-110）；
            pydantic 静默丢弃未知键（实测 model_validate OK / hasattr=False / model_extra=None）
    │
    ▼ 执行层（实际）：red_lines 仅作 prompt 文本注入（brief.py:237-240,299-302,322-325），
            靠 coder/analyst/critic 三个 LLM 的「自觉」；唯一确定性门禁 brief_coverage 只查
            「条目被回应」不查「禁令被遵守」（brief.py:254-273；routing.py:25-32）
    │
    ▼ 产物校验层：5 个 check 工具零结构消费 red_lines；check_l4_gates 的 --brief 仅文本拼接
            且 ops_review 从不传（ops_review.py:47-53）——「校验落在产物」的设计意图未实现
    │
    ▼ 弱保证落点：B16 实证的风险原样保留——红线违规仍可能「8 分压线放行」，
            因为红线最后一道确定性防线（产物扫描）不存在，只剩 LLM 评审嘴上的审查
```

即：**契约写了（v3 要求双写）→ 代码没有（schema v1 无字段，写了也被静默吞）→ 实际靠 3 处 prompt 文本注入让 LLM 自觉 + 1 个声称性门禁 → 弱保证 = 产物侧零确定性校验**。

---

## 六、若 redline_rules 落地，可能被哪些 check 消费（**推测**，基于现有结构）

> 以下为推测，未在代码中实现；判断依据是现有 check 工具的输入/输出结构与 ops_review 的聚合方式。

1. **新纯函数 `redline_violations(brief, code_artifacts, stdout_lines)`**（设计文档 02-批次1:42 已规划）：放 `src/math_agent/brief.py`，模式同 `brief_coverage_problems`（brief.py:254），由 `routing.py` 在 `after_model_code_consistency` 前叠加（02-批次1:43 规划接入点）。这是**最可能的消费路径**——对 coder 产物（代码文本 + stdout）在评分前做硬门禁，hard 违规 → retry_coder → 预算耗尽 → stop。
2. **check 脚本新增（推测）**：现有 4 个 check 都是「stdin 式单入口 + 退出码 0/1/2 + 被 ops_review 聚合」（ops_review.py:11-17, 33-63）。redline 校验可仿照做成 `scripts/check_redlines.py --brief <brief.json> --code <artifact> --stdout <out.txt>`，加入 `_CHECK_NAMES`（ops_review.py:8-16）与 `run_review` 的 argv 构造（ops_review.py:33-63）——这是成本最低的接入点，也符合「不注入 LangGraph」的既有原则（check_l4_gates 头注释「挂在操作面 S5/S7，不注入 LangGraph」）。
3. **check_l4_gates.py 的 `--brief` 参数是现成挂点（推测）**：该参数目前只做全文拼接（行 137-142），若把「brief 文本进语料」改为「解析 brief JSON 后把 redline_rules 的 pattern 注入扫描」，可复用现有语料扫描框架；但注意当前语义（防假通过）需要重设计，且 ops_review 需补传 `--brief`（目前不传）。
4. **`brief check` 命令扩展（推测）**：设计文档 02-批次1:37,54 要求 `brief check` 校验规则 schema 合法性（非法 rule_type / 缺 pattern 报错）——现 cli.py:2228-2252 只做条目计数，落地时需在此加规则级校验。
5. **result_rule 类红线（13 号 RESULT 行格式）可挂在 check_paper_numbers 同族**：其功能 B（附录 A 溯源核对）已示范「解析产物 + 与参考文件逐项断言」的范式（check_paper_numbers.py:254-310 `run_traceability`），RESULT 行 schema 比对可复用该范式（推测，未实现）。

---

## 附：证据文件清单

- `docs/archive/8-20执行批次/02-批次1-机制工程A-M3红线确定性校验.md`（设计原文，全 51 行已读）
- `docs/实现计划-8-20/8-26-M3红线机器化说明.md`（M3 说明，全 82 行已读）
- `docs/brief-playbook.md`（行 8-16 / 280-360）
- `docs/实现计划-8-20/README.md`（行 70）、`00-新题上线流程设计.md`（行 108）、`8-27-操作面契约.md`（行 195）
- `docs/archive/8-20执行批次/09-pilot模式与早期反证.md`（行 28）
- `src/math_agent/brief.py`（全文 364 行已读）、`src/math_agent/routing.py`（行 1-60）、`src/math_agent/ops_review.py`（全文）、`src/math_agent/cli.py`（行 2195-2260）、`src/math_agent/state.py`（行 133-135, 313-314）、`src/math_agent/prompts/{analyst,blueprint_critic,coder_figure_one,modeler,model_critic}.py`（grep 命中行）
- `scripts/check_paper_numbers.py`（全文 502 行）、`check_assumption_claims.py`（全文 419 行）、`check_gap_trigger.py`（全文 105 行）、`check_l4_gates.py`（全文 158 行）
- `problems/mcm51-c/brief.json`（12 字段，red_lines 13 条）
- 实测：`ModelingBrief.model_validate` 对注入 redline_rules 键的响应（静默丢弃）
- `git log -S 'redline_rules'` / `-S 'redline_violations'`（代码目录零历史命中）
