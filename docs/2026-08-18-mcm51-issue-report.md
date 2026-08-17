# 2026-08-18 MCM-51 锚杆题运行问题汇报

- 报告日期：2026-08-18
- 题目：2026 年第二十三届五一数学建模竞赛 A 题（煤矿巷道锚杆支护）
- 运行序列：`runs/51mcm-a-sens-scan`（r1）→ `...-r2` → `...-r3` → `...-r4` → `...-r5` → `...-r6`（已停止）
- 范围：仅陈述**已观测事实**与**已确定落地的解决方案**；未决项在文末"遗留风险与观察项"单列
- 提交对照：所有修复均已通过 `git commit` 记录，commit 哈希见文末对照表

---

## 一、运行记录摘要（事实）

| 运行 | 终止状态 | 终止原因 | 备注 |
|---|---|---|---|
| r1 `51mcm-a-sens-scan` | stopped（00:11:03） | 一致性门禁死锁，迭代约 30 轮 | 全 run 约 683k+ tokens、约 100 次 LLM 调用 |
| r2 `...-r2` | stopped | 无主证据轮次达到上限（6） | 验证门禁修复生效；暴露两类真实失败：除零 RuntimeWarning、KeyError |
| r3 `...-r3` | stopped | 一致性 7/10 通过但预算耗尽 | 暴露"7 分反馈死区"与"预算共用"两个机制缺陷 |
| r4 `...-r4` | stopped | paper_critic 5/10 未通过（证据链不足） | 门禁 6 轮内 8/10 通过并前进；中途 references 截断熔断，修复后 recover 完成全部章节 |
| r5 `...-r5` | stopped | 无主证据轮次达到上限（6） | 六轮失败根因同一：stdout 出现非有限数值 + RESULT 指标契约违反 |
| r6 `...-r6` | stopped（03:34:51） | paper_critic 4/10 未通过 | 一致性门禁 8/10 通过后前进至 writer；中途 worker 恢复 2 次（flash 截断 JSON）；暴露 P09–P14 |

---

## 二、问题清单与已确定的解决方案

> 编号 P01 起，后续新问题按 P11、P12… 追加，格式与本表一致。

### P01 一致性门禁死锁：指标数量硬编码与题目指标数不匹配

- **现象**：r1 一致性阶段迭代约 30 轮才停止。主证据图永远无法通过门禁。
- **根因（事实）**：
  1. `validate_numeric_results` 对主证据图硬编码要求 `min_metrics_per_result=4`，而本题 blueprint 恰好只有 3 个指标（R²、T_max、安全裕度）；
  2. coder 提示词禁止输出非本题指标名 → 模型无法补足第 4 个指标，形成**确定性死锁**；
  3. "无主证据"分支无重试上限 → 无限迭代。
- **解决方案（已落地）**：
  1. 指标下限联动 blueprint：`min_metrics = min(4, len(blueprint.metrics))`（仅主证据图）；
  2. 无主证据轮次独立上限 `MAX_CODE_NO_PRIMARY_ITERATIONS=6`（`config.py`）；
  3. 有主证据低分轮次独立预算 `MAX_CODE_VERIFY_ITERATIONS=3`，新增状态字段 `code_verify_low_score_iteration`（`state.py`，向后兼容默认 0）。
- **验证**：r4 一致性 6 轮内收敛，8/10 通过后前进；r3 起不再出现 30 轮级迭代。
- **commit**：`ac67ad6`

### P02 一致性 7 分反馈死区：被拒却拿不到审查意见

- **现象**：r3 一致性审查 7/10（门禁要求 ≥8），随后预算耗尽停机。7 分被门禁拒绝，但修复反馈阈值原为 `score >= 7` 即跳过反馈 → 模型盲重试。
- **根因（事实）**：`_consistency_repair_context` 的反馈条件（≥7）与门禁放行条件（≥8，`MIN_MODEL_CODE_SCORE`）不一致，形成"7 分死区"。
- **解决方案（已落地）**：反馈阈值对齐 `MIN_MODEL_CODE_SCORE=8`；被拒时向 coder 提供上一版主代码 + 审查 issues/suggestions 定向修复。
- **验证**：r4 中低分轮（7/10）后第 2 轮即修复至 8/10 通过，1 轮定向修复生效。
- **commit**：`ac67ad6`

### P03 无主证据失败原因不可见

- **现象**：r2 之前，面板/报告只显示"无主证据，轮次 N"，不显示具体失败原因。实际失败是：`RuntimeWarning: divide by zero in R2 = 1 - SS_res/SS_tot`（Sheet1 稀疏分组键导致每组仅 1 行、SS_tot=0）、`KeyError: '缺少锚固粘结长度参数'`（Sheet4 竖表参数名与模型猜测不一致）。
- **根因（事实）**：0/10 报告不含失败细节；观察面（watch）不展示门禁诊断正文。
- **解决方案（已落地，A+B 观测）**：
  1. 0/10 无主证据报告追加具体失败原因（最新批次 stderr，去重后至多 3 条）；
  2. 节点写入侧车文件 `gate_diagnostics.json`（原子写），supervisor 心跳合并进 `supervisor.json["gate"]`；
  3. watch 面板显示轮次、预算、超限与"疑似死循环（同一失败原因连续 N 次）"警告。
- **已知边界**：面板 gate 行不显示 `latest_issue` 正文（在 `insights/model_code_consistency.md` 中）。**用户明确暂不处理**，记录于 P10。
- **commit**：`ac67ad6`

### P04 附件数据形态导致生成代码失败

- **现象**：r2 主证据代码连续失败：
  1. Sheet1 分组键（锚杆直径）只在每组首行有值 → `dropna` 后每组仅剩 1 行 → 方差和 SS_tot=0 → 除零警告，R² 计算无效；
  2. Sheet4 为竖表参数（真实名"有效锚固长度"），数据提示只展示 2 行样例，模型猜出"锚固粘结长度"并 `KeyError`。
- **根因（事实）**：`_data_hint` 展示信息不足：窄表样例行数太少、无稀疏分组键补全指令、参数名未强调与附件一字不差。
- **解决方案（已落地）**：
  1. `_data_hint`：窄表（≤4 列）展示前 10 行样例（原 2 行）；稀疏分组键列提示 ffill 补全；竖表参数名必须与提示一字不差，缺失可选参数使用文档默认值，禁止猜测参数名；
  2. coder SYSTEM 增加数值健壮性硬性要求：SS_tot==0 / n<2 等退化输入守卫、禁止裸除法产生 RuntimeWarning/NaN、所有输出有限。
- **验证**：r2 后各轮数据读取均成功（r3–r6 未再出现同类失败）。
- **commit**：`09dce15`

### P05 参考文献章节输出截断导致同节点连续失败熔断

- **现象**：r4 writer 阶段，`references` 章节输出 14467 字符 / 8192 completion tokens，撞上模型默认输出上限，JSON 字符串截断 → `LLMValidationError` → 同节点连续失败 3 次 → supervisor `blocked`。每次失败约 5 次满额 LLM 调用（每次 ≈8k completion + 10k prompt），两次失败约 18 万 tokens 无效消耗。
- **根因（事实）**：
  1. `writer.py` 的 `complete()` 未显式设置 `max_tokens`，使用模型默认 8192（coder/modeler 均已显式设置）；
  2. references 模板只有下界"≥3 条"，无上界 → 模型无界生成。
- **解决方案（已落地）**：
  1. `_WRITER_SECTION_MAX_TOKENS=16000`，两处 `complete()`（正文与质量修复）显式传入；
  2. 模板字数预算表改为"6–12 条、每条 ≤120 字、总长 ≤2000 字符"硬性上界，并注明超限会被截断导致整节失败。
- **验证**：修复后 recover r4，references 一次通过（397 tokens / 589 字符），后续各节均短输出无截断。
- **commit**：`84df9f3`

### P06 主证据代码漏输出各子问题的关键数值

- **现象**：r4 终稿 paper_critic 5/10，8 条反馈中 4 条指向"关键定量结论缺乏证据"：问题 1.2 临界预紧力矩、问题 2.2（工况 B）Tmax、问题 3.2、问题 4 的数值结果均未在代码输出中体现，摘要却声称已求解。
- **根因（事实）**：blueprint 含 7 个子问题（`expected_output` 明确），但 coder 提示词只要求输出 4 个指标；paper_critic 以代码 stdout 为唯一数字事实源 → 正文结论无据可查。
- **解决方案（已落地）**：新增 `_subquestions_output_hint`，把 `blueprint.subquestions[].expected_output` 逐问织入主证据图提示词，强制按 `Q<id>: 字段=数值` 格式逐问打印；无法计算的子问题必须在 stdout 说明原因，不得静默跳过；支撑图不重复逐问。
- **验证**：r6 代码层已逐问输出（批次 6/7 stdout 含 Q1.1–Q4 全部数值行）；但论文证据路径曾把 Q 行剥掉（P09，已修复），r7 起评审与 writer 可见。
- **commit**：`6d04e70`

### P07 RESULT 指标契约不严格与 nan/inf 字面量输出

- **现象**：r5 六轮无主证据，失败根因同一：
  1. 模型把 `R²` 改名 `R_squared` 且只输出 3 个字段（原契约仅文字说明"一字不差"，未给完整模板，模型自由发挥）；
  2. 问题 3.2 用 `np.inf` 表示"无偏心约束"并打印，被共享门禁 `detect_output_failure` 以"输出包含非有限数值"拒绝整段 stdout。
- **根因（事实）**：
  1. 指标契约缺少"直接可抄的完整 RESULT 行模板"与"禁止改名/删减/增补"的显式约束；
  2. 提示词未明示 stdout 任何位置（含调试输出）不得出现 nan/inf 字面量。
- **解决方案（已落地）**：
  1. `_result_format_hint` 直接给出含全部 blueprint 指标标签的完整 RESULT 行模板（如 `RESULT: baseline=ours R²={m0} RMSE={m1} Tmax={m2} 安全裕度={m3}`），并明确"共 N 个、禁止改名（R² 不得写成 R_squared）/只输出一部分/增删字段"；
  2. `_result_common_hint` 明示 stdout 全部输出（调试 print、Q 行、图表标签）不得出现 nan/inf；无约束项禁止 `np.inf`/`np.nan` 占位。
- **验证**：r6 批次 6/7 stdout 已无 nan/inf 字面量（B 类误伤随"不打印原始数据"自然消失）；但批次 7 RESULT 仍只含 3 个指标（缺 RMSE、安全裕度），由 P10（数值合理性）+ P14（单位自检）覆盖，r7 验证。
- **commit**：`edf3546`

### P08 模型适用边界无合法出口（设计评审后新增协议）

- **现象（事实）**：数学模型的适用边界是真实存在的——应力公式在极端参数下根号内为负、经验公式超出适用范围时，必然产生非有限结果。此前门禁对 nan/inf 一刀切拒绝，模型被逼在"伪造数值"与"无限重试"之间二选一（r5 用 `np.inf` 表达"无偏心约束"即为此类笨拙尝试）。
- **决定**：引入"已知缺陷标注"协议（LIMITATION 声明），不要求模型完美解决边界问题，允许将其标注为已知缺陷并如实进入论文"模型局限"小节。
- **解决方案（已落地）**：
  1. stdout 可输出 `LIMITATION: <问题id> <具体数学原因>`（原因 ≥12 字符，防空洞声明）；
  2. 门禁 `validate_numeric_results`：每条 LIMITATION 声明豁免 1 个指标缺口，但至少保留一半真实指标且 ≥1 个（防凑数）；`detect_output_failure` 对 nan/inf 字面量的拒绝保留（防真 bug 传播），LIMITATION 行用文字描述原因、不得含 nan/inf；
  3. coder 提示词：禁止伪造数值凑数；LIMITATION 只用于模型数学边界，不得掩盖代码 bug（数据读取失败、除零、列名错误必须 raise）；
  4. paper_critic：LIMITATION 是合法声明，正文可写入「模型局限」小节，不算编造；但被声明字段的正文不得给出具体数值，否则仍按编造处理。
- **验证**：逻辑层测试通过（豁免/防凑数/空洞声明无效/coder 协议/paper_critic 规则共 6 项），真实场景待 r6 及后续验证。
- **commit**：`fc1874f`

### P09 论文证据白名单只认车辆路径模板前缀，MCM 题逐问输出被剥掉

- **现象**：r6 paper_critic 4/10，其中"正文声称'代码输出显示'但实际 stdout 仅有一行汇总结果"等 4 条反馈指向"编造"。但实际 stdout 中 Q1.1–Q4 逐问数值齐全（如 `Q3.2: 修正后 Tmax(e=2.0mm)=0.23 N·m`），评审误判。
- **根因（事实）**：`paper_critic._last_successful_stdout` 与 writer 侧证据路径（`_compact_code_artifacts`、`_extract_available_numbers`）共用一套**车辆路径模板专用前缀白名单**（SCENARIO_*/DYNAMIC_*/RESULT: 等）。MCM 题的逐问输出行 `Q<id>:` 与 LIMITATION 声明行全部被剥掉 → 评审与 writer 只见 RESULT 一行 → writer 无逐问数值可引（被迫扩散 RESULT 值编造细节），评审把有据可查的数值误判为编造，LIMITATION 协议在论文环节同时失效。
- **解决方案（已落地）**：
  1. `runner.structured_evidence_lines()`：模板无关白名单 = 既有前缀 + `Q<id>:` 逐问行 + `LIMITATION:` 行；
  2. paper_critic、writer 的 compact artifacts 与 available numbers 三处证据路径统一改用它，保证评审与 writer 同源；
  3. writer 增加"数值溯源硬约束"：正文数值必须逐字来自证据清单，禁止用 RESULT 行数值推断其他字段（r6 中 writer 把 Tmax=0.37 扩散到 Q1.2/Q2.1/Q3.2 等从未输出的字段），查不到就写"待验证"。
- **验证**：`structured_evidence_lines` 单测（保留 Q/LIMITATION/SCENARIO、丢弃调试行）+ paper_critic/writer 证据送达测试共 4 项；r7 真实运行验证。
- **commit**：`5e58ddb`

### P10 一致性评审放行"已知致命数值缺陷"

- **现象**：r6 一致性审查第 7 轮（03:21:08）**8/10 批准**了主证据，而其自身 issues 明确写着"Tmax=0.37 与工程经验值 100-500 N·m 严重不符""928611.38 N·m 明显不合理"。错误数值随后一路流进摘要与正文，最终由 paper_critic 拦截。
- **根因（事实）**：评审 prompt 的"严重不一致"定义只覆盖模型实现层面（变量/目标/约束/指标对齐），**不含数值合理性**；评审按"代码实现了模型"给分，忽略自己列出的数量级错误。同份代码第 6 轮得 2/10、第 7 轮得 8/10，也暴露评审随机性。
- **解决方案（已落地）**：
  1. 评审 SYSTEM 增加硬规则：数值与 blueprint validation pass_criteria / 工程合理范围严重不符（数量级错误、运行内部自相矛盾）属于严重不一致，必须 `approved=False` 且 `score<=5`；`approved=True` 需要 score≥8（与 `MIN_MODEL_CODE_SCORE` 对齐，原提示词写 7）；
  2. 确定性兜底 `_apply_numeric_fatal_backstop`：评审 issues 含"严重不符/明显不合理/数量级错误/编造/伪造"等关键词时强制不通过并封顶 5 分（r6 的 8/10 放行在此兜底下会被拦下）。
- **验证**：兜底单测 2 项（致命关键词拦截、干净报告放行）+ 提示词规则单测 1 项；r7 验证。
- **commit**：`5e58ddb`

### P11 敏感性分析代码生成静默失败（thinking 烧光 token 预算）

- **现象**：r6 sensitivity 阶段 3 次 codegen 全部返回空内容（`content: ""`、`completion_tokens=6000` 满额、`reasoning_chars=11241`），无敏感性结果 → writer 诚实声明"本文未执行定量参数扫描" → paper_critic 扣分。
- **根因（事实）**：sensitivity codegen 调用 `complete(schema=None, ...)`。`llm_worker` 只在 `response_format`（有 schema）时注入 thinking 关闭参数；`schema=None` 时模型默认 thinking，把 6000 token 预算全部烧在推理上，最终 content 为空。coder 侧因走 `schema=CoderDraft` 不受影响。
- **解决方案（已落地）**：codegen 改 `schema=SensitivityCode`（结构化输出 → 自动关 thinking + JSON 校验修复轮，代码经 JSON 往返还原换行）。
- **验证**：单测跑通（sensitivity 相关 21 项全部通过）；r7 真实运行验证。
- **commit**：`5e58ddb`

### P12 绘图任务执行成功但不产出图片，figure 流水线空转

- **现象**：r6 批次 7 三个 figure artifact（1 主 + 2 支撑）全部 `success: true` 但 `artifact_paths=[]`（无任何 .png）→ figure_pipeline 队列为空 → 论文图表数 0 → paper_critic 扣分"缺少图表"。
- **根因（事实）**：`coder_execute_node` 只校验 RESULT 协议与执行退出码，**不校验 figure 任务是否真的产出图片文件**；模型省略 `plt.savefig` 也能"成功"。
- **解决方案（已落地）**：figure 任务执行成功但工作目录无 .png → 判执行失败，反馈"必须调用 plt.savefig 保存 .png"进入定向重试。
- **验证**：`tests/nodes/test_coder.py` 8 个受影响测试更新（mock 补 artifact_paths、成功脚本补 savefig）后 34 项全过；r7 验证。
- **commit**：`5e58ddb`

### P13 flash 生成 supporting figure 时 JSON 截断，触发 supervisor 恢复循环

- **现象**：r6 两次 worker 崩溃恢复（recoveries=2，attempt 3）。崩溃点均为 `coder_generate`：flash 输出 19435 字符/12000 tokens 满额时 JSON 字符串被截断（`EOF while parsing a string at line 3 column 40447`）→ CoderDraft 校验失败 → 节点未捕获 → supervisor 按致命错误恢复。恢复后同 prompt 重试再次截断（崩溃 1 与崩溃 2 输出仅差 3 字符），每次浪费约 5 分钟与 2×12k tokens。
- **根因（事实）**：1) `_supporting_figure_model()` 在 STRONG==CODER 时退到 flash，flash 在 12000 token 上限内无法完成含 previous_code 的完整草稿；2) figure 分支的 `complete()` 无 try/except，校验失败直接炸掉 worker；3) supervisor 恢复不改变 prompt，同因必然复现。
- **解决方案（已落地）**：
  1. supporting figure 与主图统一使用强模型（STRONG_MODEL）；
  2. `coder_generate_node` figure 分支捕获生成异常：节点内有界重试（≤MAX_CODE_RETRIES），附"输出被截断/JSON 无效，请显著精简、不要复述 previous_code 全文"反馈，预算耗尽才上抛。
- **验证**：既有 coder 测试全过；r7 验证。
- **commit**：`5e58ddb`

### P14 代码输出数值数量级混乱（单位换算错误）缺少自检闸门

- **现象**：r6 主证据输出 K=0.000162（工程常规 0.1–0.3）、Tmax=0.37 N·m（blueprint validation pass_criteria 明示合理范围 100-500 N·m）、且同一次运行内 T_y_shank=928611 与 Tmax=0.37 相差 10^6 倍——P 从 kN 换算成 N 后公式混用两套单位。此缺陷同时被 P10（放行）与 P06（逐问输出已有）放大，最终由 paper_critic 捕获。
- **根因（事实）**：coder 提示词只要求"注意单位换算"，未把 blueprint 的校验标准（pass_criteria、指标单位）变成可对照的硬约束；模型无数量级自检习惯。
- **解决方案（已落地）**：coder 提示词注入"数值数量级自检"硬要求：逐条列出 blueprint validation_plan pass_criteria 与指标单位；输出 RESULT 前必须自检数量级，偏离工程常识（力矩应为数百 N·m、K 差 1000 倍）即单位换算错误，修正后再输出；同次运行数值必须自洽。
- **验证**：提示词单测 1 项；r7 验证。
- **commit**：`5e58ddb`

---

## 三、遗留风险与观察项（未决）

| 编号 | 事项 | 状态 | 说明 |
|---|---|---|---|
| O01 | 一致性轮次上限是否提升 | 观察中 | r5 六轮无主证据的失败根因同一（系统性矛盾），`routing.py` 注释明确"重试本身不会解决"。**决定：暂不提升上限**，先修根因，观察修复后收敛轮数；上限是防死循环保险，不应为系统性矛盾让路。 |
| O02 | 面板展示 `latest_issue` 正文 | 暂缓 | 用户明确：面板显示非重点，暂不处理；具体失败原因可从 `insights/model_code_consistency.md` 读取。 |
| O03 | 模型层剩余差距 | 观察中 | 51mcm 题目 paper_critic 曾指出：螺纹强度量纲、P-T 转换关系、钢带判断准则、敏感性定量扫参。r6 中量纲混乱已由 P14 提示词闸门覆盖（待 r7 验证）；其余项待 r7 结束再评估。 |
| O04 | 新题附件数据形态 | 预期内 | 每道新题可能有自己的数据坑（稀疏分组、竖表等），大概率仍需 1–2 轮"发现→修复"循环，属真实实验才能暴露的类别。 |
| O05 | 一致性评审分数随机性 | 观察中 | r6 同一份代码第 6 轮 2/10、第 7 轮 8/10。P10 兜底已把"自认致命缺陷仍批准"拦下，但分数抖动仍可能影响收敛轮数；若 r7 收敛轮数异常再考虑提示词加固。 |
| O06 | 主证据数值质量依赖模型自检 | 观察中 | P14 是提示词层约束，不是确定性校验；blueprint pass_criteria（如 100-500 N·m）的数值区间尚未做机器可读提取与确定性门禁。若 r7 仍出现数量级错误，升级为解析 pass_criteria 区间 + 确定性拦截。 |
| O07 | worker 恢复机制成本 | 已修复 | r6 两次恢复均为 P13 根因（flash 截断），修复后预计不再触发；恢复机制本身工作正常（checkpoint 无损续跑），保留观察。 |

---

## 四、Git 提交对照表（本报告覆盖的修复）

| commit | 主题 |
|---|---|
| `1316be8` | feat(observation)：insights/steps 机制快照与 CLI 终态区分 |
| `6985f5d` | feat(llm)：空 content 自动提 max_tokens、thinking 关闭与超时档位加固 |
| `ac67ad6` | fix(gate)：一致性门禁修复与死锁防护（P01/P02/P03，A+B 观测） |
| `09dce15` | fix(prompts)：附件数据提示与提示词加固（P04） |
| `84df9f3` | fix(writer/sensitivity)：参考文献截断修复与敏感性诚实稿（P05） |
| `6d04e70` | fix(coder)：主证据图逐问输出 expected_output，禁止截断掩盖负值（P06） |
| `edf3546` | fix(coder)：RESULT 指标契约一字不差 + 禁止 nan/inf 输出（P07） |
| `fc1874f` | feat(gate)：LIMITATION 声明协议（P08） |
| `5e58ddb` | fix(r6)：论文证据白名单、数值合理性门禁、sensitivity/figure/coder 韧性（P09–P14） |

测试基线：修复后全量回归 `688 passed / 4 skipped`（排除本环境无法运行的 subprocess 相关测试）。

---

## 五、后续追加说明

- 新发现的问题请按 **P11、P12…** 追加到第二节，保持"现象 / 根因（事实）/ 解决方案（已落地）/ 验证 / commit"结构；
- 观察项按 **O05、O06…** 追加到第三节；
- 每笔修复落地后更新第四节提交对照表，并同步更新第二节对应条目的 commit 与验证字段；
- 本报告只收录**已观测事实**与**已确定方案**；推测性内容一律放入观察项并在说明中标注"未验证"。
