<!-- 全流程分析 · brief 检查系列 · 01 · 2026-08-29 · 操作面 S4–S8 与 CLI 层 brief 真实消费路径（源码核实，只读） -->

# 01 操作面 S4–S8 的 brief 消费路径

> **来源**：2026-08-29 委派核查——「brief 真实调用检查」待查项 [x]（操作面 S4/S5/S6/S7 的真实消费路径，不止流水线注入）。本文只读源码核实（`src/math_agent/`、`scripts/`），行号基于当日工作区。
> **结论一句话**：操作面对 brief 的消费**只有两处半**——S3 阶段判定只看文件存在；S6 `reference paper/expand` 读 `required_discussions` 与 `per_question_direction` 两个字段；S4/S5/S7/S8 及全部四个校验脚本**零字段消费**。brief 的其余 6 个字段（red_lines/formula_notes/figure_plan/scoring_notes/data_notes/reference_direction）在操作面**完全不接触**，只活在 S9 流水线 prompt 注入里。

---

## 一、CLI 层 brief 接触面总览（src/math_agent/cli.py）

| 位置 | 内容 | 性质 |
|---|---|---|
| cli.py:309-320 | `_write_run_manifest` 写入 `brief_sha256` | 证据链（哈希冻结） |
| cli.py:328-335 | `_load_brief_or_raise`：加载即 schema 校验 | 入口校验 |
| cli.py:337-343 | `_copy_brief_to_out`：brief 原文复制到 `out/brief.json` | 证据链 |
| cli.py:407-410 | `brief_app` 注册（init/check/dialogue 三子命令） | S3 工具 |
| cli.py:1065-1078 | `_load_paper_brief`：`--brief` 缺省尝试 `problems/<id>/brief.json` | S6 装配 |
| cli.py:1104-1126 | `_paper_assumptions`：**读 `required_discussions`**（仅 `disc-assumptions` 条目） | **消费** |
| cli.py:1139-1149 | `_question_direction`：**读 `per_question_direction`**（按 question_id 取 direction 首句） | **消费** |
| cli.py:1336-1420 | `_build_paper_md` 骨架装配（1372 假设来源注明；1391-1397 方向行） | **消费** |
| cli.py:1452-1580 | `reference paper`（S6 骨架）：`--brief` 1461-1463；`brief_data` 1524 传入骨架 | **消费** |
| cli.py:1587-1730 | `reference expand`（S6 展开）：`--brief` 1600-1602；`brief_data` 1652 传入 `expand_paper` | **消费** |
| cli.py:1732-1800 | `reference verify`（S5 登记）：**无 `--brief`** | 不消费 |
| cli.py:1801-1867 | `reference recertify`（S5 复核）：**无 `--brief`** | 不消费 |
| cli.py:1874-1921 | `accept`（S8 人审登记）：**无 `--brief`** | 不消费 |
| cli.py:1922-1970 | `review-check`（S7 评审）：**无 `--brief`**（仅 `--paper/--evidence/--gap-json/--traceability/--strict`） | 不消费 |
| cli.py:2068-2069 | `problem import` 提示文案（下一步 brief init） | 文案 |
| cli.py:2076-2100 | `problem show`：brief 存在性 + sha256 前 12 位（2095-2100） | 展示 |
| cli.py:2144-2154 | `_write_brief_file`：`brief init` 原子写入 | S3 工具 |
| cli.py:2156-2188 | `_brief_problem_mismatch` / `_warn_brief_problem_mismatch`：**读 `brief.problem_id`** 与题目标题宽松比对，不匹配仅 WARN | 防误用（不阻塞） |
| cli.py:2193-2224 | `brief init`（空白模板） | S3 工具 |
| cli.py:2226-2247 | `brief check`（schema 校验 + 条目统计，见 §六） | S3 工具 |
| cli.py:2249-2329 | `brief dialogue`（TTY 交互生成，非做题路径） | S3 工具 |
| cli.py:2335-2376 | `_dry_run_preflight`：brief 只展示路径与条数（2358-2360），不校验内容 | S4 展示 |
| cli.py:2379-2443 | `run`：`--brief` 2384-2385；加载+sha256+WARN 2400-2405；**注入 state.brief 2421**；复制 2441-2442；manifest 2443 | S9 入口（唯一把 brief 送进流水线的地方） |
| cli.py:2960-2992 | `restart`：输入不变性校验，`out/brief.json` 与 manifest `brief_sha256` 对照（2980-2990） | 证据链 |
| cli.py:3140-3195 | `supervise`：`--brief` 3145-3146，透传 3179-3180 | S9 入口 |
| cli.py:3200-3237 | `start`：`--brief` 3205-3206，透传 3233-3234 | S9 入口 |
| cli.py:3349-3420 | `supervise-resume` / `supervise-recover`：**无 `--brief`**（从 checkpoint 恢复，brief 已在 state 内） | 不消费 |

## 二、操作面逐文件核查（src/math_agent/ops_*.py）

| 文件 | 阶段 | brief 痕迹 | 结论 |
|---|---|---|---|
| ops_preflight.py | S4 | 24 行 `brief_path` 参数；73 行仅 `str(brief_path)` 记入 preflight.json | **不消费字段**。预检不读 brief 内容；真正的 brief 校验发生在 CLI 层 `_load_brief_or_raise`（cli.py:328-335），且 `brief_path` 只是字符串回显 |
| ops_verify.py | S5 | 无 | **零接触**。evidence-package 三项检查（run_success/no_nan_inf/has_result）与 brief 无关 |
| ops_recertify.py | S5 | 无 | **零接触**。独立复核只比对数值（rerun 对照） |
| ops_accept.py | S8 | 无 | **零接触**。acceptance.json 只含 paper sha256 + approved |
| ops_stage.py | S6 判定 | 25 行 `"S3": ["brief.json"]`（缺失清单）；147 行 S3 完成 = `brief.json` 文件存在 | **只查存在性**，不读任何字段 |
| ops_handoff.py | S6 交棒 | 66 行 S3 交棒 `brief check`；70-71 行 S4 交棒带 `--brief`；79-81 行 **S6 交棒 `reference paper` 不带 `--brief`**；87-93 行 S7 交棒不带 | **交棒口子隐式消费**：S6 命令本身支持 `--brief` 且缺省自动尝试 `problems/<id>/brief.json`（cli.py:1068），故交棒省略不致命，但未显式传参 |
| ops_review.py | S7 | **无**（全文 grep 零命中） | **零接触**。`--evidence` 只透传给 check_paper_numbers（74-75 行）；不传 brief（详见 §五） |
| ops_help.py | — | 13/24/32 行（帮助文案，dialogue 标注非做题路径） | 文案 |
| ops_gate.py | — | 无 | 零接触 |

## 三、scripts/check_*.py 核查

| 脚本 | brief 接触 | 说明 |
|---|---|---|
| check_paper_numbers.py | 无（grep 零命中） | 数字溯源核心。`--evidence` 白名单 = **证据文件中的数字 token**（98-129 行 `load_evidence_whitelist`），与 brief 完全无关 |
| check_assumption_claims.py | 仅注释（9/55 行示例路径 `runs/mcm51-b-brief-v1/`） | 不读 brief |
| check_gap_trigger.py | 无 | 只吃 `--json` 证据 |
| check_l4_gates.py | **有 `--brief` 参数**：29 行用法；111 行 argparse；137-142 行把 brief 全文并入扫描语料 | ⚠️ **操作面死参数**：`ops_review.run_review` 调它时只传 `--paper`（ops_review.py:89-93），从未传 `--brief`；仅手动调用脚本时才生效 |
| check_doc_newlines.py | 无 | 文档治理脚本 |

## 四、tools/ 与 nodes/ 核查

- `src/math_agent/tools/`（image.py / latex_compile.py / references.py / runner.py / scholar.py）：**全部无 brief**。
- `nodes/evaluation.py`：**无 brief**（grep 零命中）。其 SYSTEM 提示词 `prompts/evaluation.py:20` 有「若提供评分细则/得分点清单则逐条核对」分支，但 `build_prompt`（prompts/evaluation.py:27 起）**无任何 brief/scoring 参数** → 永久死路径（与 `子agent分析/03-scoring_notes注入评估.md` 一致，操作面无关）。
- `nodes/human_review.py`：**无 brief**（只处理 human_decision）。
- S9 侧对照（brief 真正被消费的地方，供区分）：`state.py:313-314`（state.brief）、`nodes/analyst.py:32` 与 `nodes/blueprint_critic.py:26`（渲染器注入）、`routing.py:25-29` + `brief.py:174-195`（brief_coverage 门禁）、`brief.py:74-82`（7 个条目字段）。

## 五、结论表：操作面各阶段 × brief 消费矩阵

| 阶段 | 消费？ | 证据 | 说明 |
|---|---|---|---|
| S3 方向收敛 | 存在性（仅） | ops_stage.py:25,147 | 阶段判定只看 `brief.json` 文件在不在；内容由 `brief check` 校验（cli.py:2226-2247，只验 schema 不读业务字段） |
| S4 预检 | **不消费字段** | ops_preflight.py:24,73；cli.py:2335-2376 | preflight.json 只回显 `brief_path` 字符串；brief 校验在 CLI 层加载时完成（cli.py:328-335），预检本身不检查 brief 内容 |
| S5 求解验证 | **不消费** | ops_verify.py、ops_recertify.py 全文无 brief | evidence-package / independent-review 与 brief 无任何关系 |
| S6 登记装配 | **消费 2 字段** | cli.py:1104-1126,1139-1149,1372,1391-1397；paper_expand.py:197-207 | `reference paper/expand` 读 `required_discussions`（仅 disc-assumptions，进模型假设节）与 `per_question_direction`（方向一句话，进各问摘要）；缺省自动尝试 `problems/<id>/brief.json`（cli.py:1068）。⚠️ 交棒命令不显式传 `--brief`（ops_handoff.py:79-81），靠缺省路径隐式命中 |
| S7 评审 | **不消费** | ops_review.py 全文无 brief；cli.py:1922-1970 | review-check 的四个 checker 均不读 brief；`check_l4_gates` 虽有 `--brief`（check_l4_gates.py:111,137-142）但 S7 包装从未传参（ops_review.py:89-93）→ 死参数 |
| S8 人审登记 | **不消费** | ops_accept.py 全文无 brief；cli.py:1874-1921 | acceptance.json 只登记 paper sha256 + approved，无 brief 关联字段 |
| S9 流水线（对照） | **全量消费** | state.py:313-314；analyst.py:32；blueprint_critic.py:26；routing.py:25-29；brief.py:74-82,163-195 | 7 个条目字段的 id 全部进 brief_coverage 门禁；字段内容按节点裁剪注入（见 `brief真实调用检查.md` 注入矩阵） |

### 特别标注：S7 评审的 `--evidence` 白名单机制与 brief 的关系

**完全无关，brief 的 figure_plan/data_notes 不影响评审清单**。证据链：

1. `review-check --evidence`（cli.py:1929-1930）→ `ops_review.run_review`（ops_review.py:73-75）→ `check_paper_numbers --evidence`；
2. 白名单 = 证据文件的**数字 token**（check_paper_numbers.py:98-129 `load_evidence_whitelist`：`--evidence` 可传 md/txt/json，键和值都进白名单）；
3. 评审清单因此只覆盖「数字溯源」，与 brief 的 figure_plan（必做图清单）、data_notes（数据注意）没有任何映射关系——brief 里规划的图/数据口径是否兑现，S7 机器评审**看不见**，只能靠 S8 人工在 `--notes` 里自查。
4. 若给 `check_l4_gates` 手动传 `--brief`（check_l4_gates.py:137-142），brief 全文并入扫描语料后反而可能成为 G1–G3 的触发/通过源——但 S7 自动路径从不传，该行为仅手动可用。

## 六、附：cli.py:2244「brief 条目统计」数的是什么

`brief check`（cli.py:2226-2247）输出 `共 {len(ids)} 条待回应条目`，其中：

- `ids = brief_item_ids(obj)`（cli.py:2239）→ brief.py:163-172：**按字段声明顺序遍历 7 个条目字段**（`_BRIEF_ITEM_FIELDS`，brief.py:74-82：per_question_direction / formula_notes / required_discussions / red_lines / figure_plan / scoring_notes / data_notes），**每个条目（item）算 1 条**；
- `reference_direction` 是 `list[str]`（无 id，brief.py:106），**不计入**；
- 「待回应」的含义：这 7 个字段的每条 id 是 S9 `blueprint.brief_coverage` 门禁必须逐条回应的对象（routing.py:25-29 + brief.py:174-195，followed 或 deviated+理由，缺条目/无理由偏离 → retry/stop）——即**这个数字是 S9 门禁的规模指标，与操作面 S4–S8 无关**；
- 2246 行另有 WARN：`brief` 全为空时提示「不会注入任何约束」。

## 七、关键发现汇总

1. **操作面 brief 真实消费 = S6 两字段 + S3 存在性**，其余阶段（S4/S5/S7/S8）零字段消费。
2. **S7 评审与 brief 完全脱钩**：白名单只数证据数字；figure_plan/data_notes 对评审清单零影响（图/数据口径兑现只能靠 S8 人工）。
3. **`check_l4_gates --brief` 是操作面死参数**（S7 包装不传），与 evaluation「评分细则分支」死路径同款——两个承诺了 brief 输入的点都没有真实接线。
4. **S6 交棒不显式传 `--brief`**（ops_handoff.py:79-81），靠 `problems/<id>/brief.json` 缺省路径隐式命中；若 brief 只放在别处则 S6 静默降级为「假设/方向用【待展开】占位」（cli.py:1383）。
5. **brief 哈希闭环只存在于 S9 入口**（run/supervise/start 写 manifest，restart 校验），操作面 S5–S8 产物（evidence-package/review-report/acceptance）都不带 brief 指纹，无法事后核对「评审/登记时用的 brief 是哪一版」。

## 待查（衔接既有清单）

- [ ] brief_coverage 门禁与 40 条逐条覆盖的真实行为（流水线侧，另文）
- [ ] brief check 校验范围（哪些字段只 WARN 不阻断）——需读 brief.py load_brief 校验细节
- [ ] S7 评审清单是否应纳入 figure_plan/data_notes（机制缺口，供决策登记）
