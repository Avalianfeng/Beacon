# Modeling Brief（建模预备 A2）实施计划书与交接文档

- 建立日期：2026-08-19
- 关联：《体系流程优化报告》（`docs/09-体系流程优化报告.md` 方案 A2）、
  《MCM-51 迭代计划》（`docs/08-MCM51整改迭代计划.md`）
- 定位：**跨平台交接计划书**。本次会话已完成全部设计决策与大部分编码；
  本文档记录：① 已拍板的设计决策；② 完整设计（计划书主体）；③ 已执行部分（文件级 + 验证证据）；
  ④ 未执行部分（接手者按序执行）；⑤ 当前工作区状态与紧急修复指引；⑥ 重要注意事项。
- 事实基线：git `f70fc7e`（A2 设计落文档）；测试基线 708 passed / 4 skipped（2026-08-18，本次改动前）
- 现状（T7 收口）：**`cli.py` 语法错误已修复**（`except` 补 `pass`、删除 `dialogue` 后孤立 `pass`）；
  `nodes/blueprint_critic.py` 本轮已补传 `brief=state.brief`；前端透传、测试与 `docs/problems/mcm51-a/brief.json` 已落地；
  **全量回归已跑**：778 passed / 12 failed / 4 skipped（相对 708 基线 +70 passed）；12 失败为既有管线/coder/recovery/smoke，非 `test_brief.py`；**尚未 commit**（见第五节、第七节）。

---

## 一、背景与目标

MCM-51 锚杆题 r1–r11 实证：体系"知识闭包"（题面 + 附件摘要 + 预训练 + 反馈循环）内
**方向级盲区不可达**（变点检测、调心垫圈、围岩分级等 7 项盲区全部是"外部资料写明、体系无法获取"），
当前约 35–40/100 分，其中 1.2/3.1/3.2/4 四项合计 40 分基本空白，属于方向级错误。

**目标**：任务开始前，由人 + AI 对话产出 `brief.json`（八字段：逐题方向/公式注意/讨论点/
红线/图表/评分/数据注意/文献方向），注入流水线，在源头杜绝方向性错误。
前置对话在 CLI/Web 层，**不进 LangGraph 主图**（主图结构不变、向后兼容）。

**分层认知（范围控制的依据）**：
- 方向级错误（为什么这样建模、论文怎么论述）→ 靠前置深思（人机对话），流水线内不再交互；
- 实现级错误（公式/参数/单位）→ 放心交给现有后置门禁（critic/consistency），不重复设计。

---

## 二、已拍板的设计决策（用户确认）

| # | 决策点 | 结论 | 说明 |
|---|---|---|---|
| 1 | 门禁预算耗尽后的行为 | **硬停（`stop`）** | analyst 重试耗尽仍不满足 brief_coverage → 终止流水线并报错；brief 是人工高价值输入，带病前进会烧掉整轮预算；checkpoint 已存；**修 prompt（代码）可 `recover` 续跑（沿用 checkpoint 内旧 brief）；修 brief 只能全新 `run`（新 `--out` 或 `--force`）**；`recover`/`supervise-resume`/`supervise-recover` 均不接受 `--brief`；门禁 `stop` 后 checkpoint `next=()`，`recover` 为空转 |
| 2 | Web 层范围（本迭代） | **仅透传已有 brief.json** | 前端启动生成时可选指定 brief 文件，`server.mjs` 透传 `--brief`；对话式建模预备 UI 明确后置（**用户注明：后续真实使用必然要做对话 UI**） |
| 3 | `--assist` 对话式生成 | **纳入本迭代** | CLI `brief dialogue --assist`：每字段 LLM 起草 + 人工确认；模板（`init`）+ 校验（`check`）为兜底 |
| 4 | 体系内是否"再评估"前置工作 | **加"防忽略校验"，不加"方向再评估"** | 方向正确性只在前置对话确定；`brief_coverage` 门禁是**传递完整性校验**（brief 条目有没有被 analyst 转述进 blueprint、deviated 是否给理由），不是评审方向对错。方向错了的反馈回路 = 回到前置对话修订 brief 重跑。**C2 已采纳（2026-08-20）**：禁止无依据 LLM 投票式方向评审；允许基于确定性证据（残差/量纲/边界/对照实验）的方向反证（落地见 16 阶段 2） |
| 5 | 评审节点对 brief 的职责 | 收敛为**机械覆盖 + 实现级检查** | blueprint_critic/model_critic 只查"brief 条目是否被转述/公式注意与红线是否被遵守"（实现级），不评审方向本身 |
| 6 | 兼容与安全 | `--brief` 可选；**题面 > brief > 预训练直觉** | 人工指引与题面冲突时以题面为准并在 brief_coverage 标注"偏离 + 理由"；不破坏现有门禁与证据链 |

---

## 三、完整设计（计划书主体）

### 3.1 brief.json schema（八字段 + brief_coverage）

```json
{
  "schema_version": 1,
  "problem_id": "mcm51-a",
  "created_at": "2026-08-19T00:00:00+00:00",
  "source": ["official_standard", "human"],
  "per_question_direction": [
    {"id": "1.2-direction", "question_id": "1.2",
     "direction": "必须变点检测/分段回归", "forbidden": "禁止用工况A参数直接算临界值"}
  ],
  "formula_notes": [
    {"id": "2.2-fbond", "question_id": "2.2",
     "note": "F_bond=π·D_hole·L_bond·τ（钻孔直径，非锚杆直径）"}
  ],
  "required_discussions": [
    {"id": "3.1-e0", "sections": ["model_section", "solution"],
     "topic": "e=0 参考线意义与 233% 解读", "requirement": "必须出现"}
  ],
  "red_lines": [
    {"id": "1.2-600", "question_id": "1.2", "prohibition": "不得硬编码 600.71/0.8·T_max"}
  ],
  "figure_plan": [
    {"id": "fig6", "question_id": "3.1", "figure": "T_max-e 曲线", "requirements": "三条线+e_cr 标注"}
  ],
  "scoring_notes": [
    {"id": "1.2-tc", "question_id": "1.2", "note": "T_c∈[100,150] ±5% 容差"}
  ],
  "data_notes": [
    {"id": "1.2-mean", "question_id": "1.2", "note": "表2/3 五测点均值化"}
  ],
  "reference_direction": ["巷道支护", "Winkler 地基", "螺纹力学"]
}
```

设计要点：
- **每条目带稳定 `id`**（如 `1.2-direction`），供 `brief_coverage` 逐条引用——门禁确定性的前提；
- `required_discussions.sections` 白名单：`abstract|problem_restatement|assumptions|notation|model_section|solution|sensitivity|conclusion|references`（writer 按分组过滤注入）；
- `source` 来源分级约定：`official_standard`（官方文件）> `human`（人工整理）> `model_draft`（模型推演）；
- 可选字段留空数组即跳过；空条目不进门禁；
- `problem_id` 与题目 title 宽松匹配，不匹配仅警告（`_warn_brief_problem_mismatch`）。

**brief_coverage 回应格式**（analyst 的 ProblemBlueprint 内新增字段，复制 modeler question_coverage 机制）：

```json
"brief_coverage": [
  {"brief_item_id": "1.2-direction", "status": "followed", "reason": ""},
  {"brief_item_id": "2.2-fbond", "status": "deviated", "reason": "与题面冲突，以题面为准"}
]
```

### 3.2 State 与运行产物

- `MathModelingState.brief: ModelingBrief | None = None`（覆盖语义、run 启动时确定；旧 checkpoint 默认 None）；
- `ProblemBlueprint.brief_coverage: list[BriefCoverageItem]`（默认空列表，旧数据兼容）；
- `run_manifest.json` 增加可选 `brief_sha256`；
- run 输出目录落 `out/brief.json` 副本（证据链可审计，`_copy_brief_to_out`）。

### 3.3 CLI

1. `run` / `supervise` / `start` 增加可选 `--brief <path>`：`_load_brief_or_raise` 读取校验，
   无效 → BadParameter 明确报错；supervise/start 前置校验后把 `--brief` 拼进子进程 args（resolve 绝对路径）。
2. 新命令组 `math-agent brief`（模块 `brief_dialogue.py` 提供对话逻辑）：
   - `brief init --problem <spec> --out <path> [--force]`：空白模板；
   - `brief check --brief <path>`：schema 校验（纯校验，不调 LLM）；
   - `brief dialogue --problem <spec> --out <path> [--assist/--no-assist] [--force]`：
     逐字段问答；`--assist` 时 LLM（`STRONG_MODEL`）按题面 + `build_data_summary_hint`
     数据摘要起草，人工确认/修改；`auto_fill_ids` 自动补全缺失 id；落盘前 `ModelingBrief.model_validate`。
3. 沉淀路径：`docs/problems/<题号>/brief.json`（跨题复用，衔接知识沉淀通道）。

### 3.4 六处注入点（文件级）

| 注入点 | 文件 | 注入内容 |
|---|---|---|
| analyst | `prompts/analyst.py` + `nodes/analyst.py` | 完整 brief 块；SYSTEM：优先级"题面 > brief > 直觉"、逐条回应要求；schema hint 加 `brief_coverage`；节点传 `state.brief` |
| blueprint_critic | `prompts/blueprint_critic.py` + `nodes/blueprint_critic.py` | 完整 brief 块 + "未覆盖记 issue；deviated 必须给理由"（第 8 条检查项）；节点传 `state.brief` |
| model_critic | `prompts/model_critic.py` + `nodes/model_critic.py` | `render_critic_brief`（公式注意 + 红线）作**实现级评审基准**："违反记 issue（不评审方向本身）" |
| modeler | `prompts/modeler.py` + `nodes/modeler.py` | `render_modeler_brief`（逐题方向 + 公式注意）作路线选择约束 |
| coder | `prompts/coder_figure_one.py` + `nodes/coder.py` | `render_coder_brief`（红线 + 公式注意）："红线违反即失败" |
| writer | `prompts/writer_section.py` | `build_section_prompt` 渲染后追加"人工建模预备要求（讨论点必须体现）"块，按分组过滤 `required_discussions`（追加块模式，7 个模板文件零改动） |

容量控制：每条 ≤200 字符、整块 ≤1500 字符级（信息过载对策）。

### 3.5 门禁（确定性校验）

`brief.py::brief_coverage_problems(brief, blueprint) -> list[str]` 纯函数：
- brief 为 None → `[]`（恒通过，向后兼容）；
- 每条目 id 必须出现在 `blueprint.brief_coverage`：`followed` → 通过；
  `deviated` 且 reason 非空 → 通过（显式偏离）；缺失或 deviated 无理由 → 记问题。

接入 `routing.after_blueprint_critic`：有 problems 且 `blueprint_iteration < MAX_BLUEPRINT_ITERATIONS(=2)`
→ `retry`；预算耗尽仍有 problems → **`stop`**。`graph.py` 唯一改动：blueprint_critic 条件边增加
`"stop": END`（不新增节点；仅启用 brief 时可达）。

### 3.6 兼容性核对（已逐项核实）

- 无 `--brief`：注入块不渲染、门禁返回 `[]`、graph 原路径 → 行为逐字节一致；
- 旧 checkpoint（无 brief 字段）→ None；`recover`/`supervise-resume`/`review` 不触碰 brief；
- 旧 ProblemBlueprint（无 brief_coverage）→ 默认空列表；
- 旧 run_manifest（无 brief_sha256）→ `.get()` 容错。

---

## 四、已执行部分（文件级 + 验证证据）

### 4.1 已修改/新建文件清单

| 文件 | 状态 | 内容 |
|---|---|---|
| `src/math_agent/brief.py` | ✅ 新建（LF） | `ModelingBrief` 八字段 schema + `BriefCoverageItem` + `load_brief` + `brief_item_ids` + `brief_coverage_problems`（门禁纯函数）+ 五个渲染 helper（full/modeler/coder/critic/discussions_for_group） |
| `src/math_agent/brief_dialogue.py` | ✅ 新建（LF） | `FIELD_SPECS`（八字段定义+示例）、`build_context`、`draft_field`（LLM 起草，失败返回 None）、`auto_fill_ids`、`assemble_brief` |
| `src/math_agent/state.py` | ✅ 已改 | import brief；`ProblemBlueprint.brief_coverage`；`MathModelingState.brief` |
| `src/math_agent/cli.py` | ✅ 已改（T7 修复） | `run/supervise/start --brief` 参数、`_write_run_manifest` brief_sha256、`_load_brief_or_raise`/`_copy_brief_to_out`/`_warn_brief_problem_mismatch`/`_write_brief_file`；`brief` 命令组（init/check/dialogue）；**语法错误已修**（`except` 补 `pass`、删 dialogue 后孤立 `pass`，见第六节） |
| `src/math_agent/prompts/analyst.py` | ✅ 已改 | SYSTEM brief 约束 + schema hint + `build_prompt(brief=None)` + brief 块渲染 |
| `src/math_agent/nodes/analyst.py` | ✅ 已改 | 传 `brief=state.brief` |
| `src/math_agent/prompts/blueprint_critic.py` | ✅ 已改（早前） | SYSTEM 严重问题定义 + `build_prompt(brief=None)` + brief 块 + 第 8 条检查项 |
| `src/math_agent/nodes/blueprint_critic.py` | ✅ 本轮已改 | **补传** `brief=state.brief`（此前 prompt 已就位，节点曾漏传） |
| `src/math_agent/prompts/model_critic.py` | ✅ 已改 | `build_prompt(..., brief=None)` + brief_block（实现级基准） |
| `src/math_agent/nodes/model_critic.py` | ✅ 已改 | 传 `brief=state.brief` |
| `src/math_agent/prompts/modeler.py` | ✅ 已改 | `build_prompt(..., brief=None)` + brief_block（方向+公式） |
| `src/math_agent/nodes/modeler.py` | ✅ 已改 | 传 `brief=state.brief` |
| `src/math_agent/prompts/coder_figure_one.py` | ✅ 已改 | `build_prompt_figure_one(..., brief=None)` + brief_hint（红线） |
| `src/math_agent/nodes/coder.py` | ✅ 已改 | 调用处传 `brief=state.brief` |
| `src/math_agent/prompts/writer_section.py` | ✅ 已改 | `build_section_prompt` 追加讨论点块（按分组过滤） |
| `src/math_agent/routing.py` | ✅ 已改 | `after_blueprint_critic` 门禁（retry → 预算耗尽 stop） |
| `src/math_agent/graph.py` | ✅ 已改 | blueprint_critic 条件边 `{"retry","advance","advance_with_warning","stop": END}` |

### 4.2 验证证据

- 上述 Python 源文件（含 cli.py）`py_compile` 全部通过；
- 相关既有测试 **120 passed**（`tests/test_routing.py`、`tests/nodes/test_analyst.py`、
  `test_blueprint_critic.py`、`test_model_critic.py`、`test_modeler.py`、`test_writer_per_section.py`、
  `tests/test_state.py`、`tests/test_cli.py`；耗时 1.99s）——跑在 cli 语法修复与 `brief` 命令组就位之前；
- **新增** `tests/test_brief.py`，并扩展 `tests/test_routing.py`、`tests/test_cli.py` 等（mock LLM，不联网）；
- 前端 `npm.cmd test -- --run`：brief 透传相关场景已通过（见第五节第 2 项）；
- **全量回归**（`.venv\Scripts\python.exe -m pytest -q`，约 92s）：**778 passed / 12 failed / 4 skipped**（相对 708 基线 **+70 passed**，skipped 仍为 4）；**不宣称全绿**；12 失败见第五节；
- **未 commit**（工作区仍为 dirty，见第七节 7.3）。

---

## 五、未执行部分（接手者按序执行）

- [x] **紧急修复 `cli.py` 语法错误**（见第六节，**已执行**）：`py_compile` + `math-agent brief --help` + `tests/test_cli.py` 已可跑；
- [x] **前端透传**（Web 本迭代范围 = 仅透传）：
  - `frontend/server.mjs`：`supervise` args 拼装 `body.briefPath` → `--brief`；
  - `frontend/app.js` / `index.html`：启动表单可选 brief.json；
  - `frontend/server.test.mjs`：透传场景测试；`npm.cmd test -- --run` 已跑（brief 相关场景绿）；
- [x] **文档沉淀**：
  - `docs/problems/mcm51-a/brief.json`：八字段已填写，`brief check` 可验；
  - `docs/README.md`：索引条目已更新（文首质量基准段未动）；
  - `docs/2026-08-19-modeling-brief.md`（独立实施说明）：**可选**，本计划书已含主体设计；
- [x] **新增测试**（全部 mock LLM，不联网）：
  - `tests/test_brief.py`：schema / `brief check` / 门禁纯函数；
  - `tests/test_routing.py` 扩展：retry / stop / 无 brief 原路由；
  - 注入参数化、节点级 analyst、CLI `run --brief` / supervise args、`brief init/check` 等（见各 test 文件）；
- [x] **全量回归已跑**（`.venv\Scripts\python.exe -m pytest -q`）：**778 passed / 12 failed / 4 skipped**。brief 相关单测计入 passed。12 失败（**不是** `test_brief.py`）：`tests/bench/test_runner_mock.py`、`tests/integration/test_granular_recovery.py`×3、`tests/nodes/test_coder_multi_figure.py`×4、`tests/nodes/test_finalizer.py`、`tests/nodes/test_writer_recover.py`、`tests/test_graph_full_smoke.py`、`tests/test_graph_smoke.py`（未写出 paper.md/tex）。计划约定失败只报证据、不盲改冻结代码。**验收「全量绿」未达成**；
- [x] **清理** `.tmp_brief_edits/`（T7 已删，见交接回报）；
- [ ] **`git commit`**（建议按第四节清单分组提交）+ 全量回归绿后更新本文档为最终"已执行"状态。

---

## 六、紧急修复指引（cli.py）——**已执行（T7）**

> 接手者**无需**再执行本节；下列为当时故障记录与修复步骤，仅供追溯。

**当时现状**（已用原始字节确认）：
- 行 363：`    except Exception:`（`_prepare_run_output` 的 except，**body 丢失**）；
- 行 364–367：`brief_app = typer.Typer(...)` 块以 **0 缩进**跟在 except 后
  → `SyntaxError: expected an indented block after 'except'`；
- 行 370 起 `_write_brief_file`/`_warn_brief_problem_mismatch`/`@brief_app.command(...)` 三个命令
  均已在正确位置（模块级）；行 535-536 `@app.command()` + `def run(` 及 `--brief` 参数完好。

**修复（一个替换即可）**：把

```
    except Exception:
brief_app = typer.Typer(
```

替换为

```
    except Exception:
        pass


brief_app = typer.Typer(
```

即：补回 8 空格 `        pass`（except 的 body）+ 空两行，`brief_app` 块回到模块级。
其余内容**不要动**（run/supervise/start 的 `--brief` 与 manifest/helper 全部正确）。

**验证**（T7 已通过）：`python -m py_compile src/math_agent/cli.py` → `math-agent brief --help` → `pytest tests/test_cli.py`。

**编辑方法注意**：cli.py 为 CRLF；本会话 edit/write 工具对已存在文件间歇性
`ReplaceFileW EIO`。建议用 Python 脚本：`read_text()`（universal newlines）→
`text.count(old) == 1` 断言 → `replace` → `write_text(text.replace("\n", "\r\n"))` 写回 CRLF。

---

## 七、重要注意事项（接手者必读）

### 7.1 环境与工具

- **git**：仓库属 `BUILTIN/Administrators`，当前用户访问需 `git -c safe.directory='*' -C E:\git_clone\Beacon ...`
  （或 `git config --global --add safe.directory E:/git_clone/Beacon`，但全局 .gitconfig 可能无权限）；
  `git.exe` 偶发"拒绝访问"（ResourceUnavailable），重试即可；
- **uv**：`C:\Users\m1995\AppData\Local\uv\cache` 无权限（另一用户目录）→ `uv run` 可能失败；
  直接使用 `.venv\Scripts\python.exe`（仓库内 venv）；
- **python spawn**：PowerShell `&` 调用 python.exe 偶发"拒绝访问"，重试或 `cmd /c` 可解；
  之前 `.venv\Scripts\python.exe -m py_compile ...` 与 `-m pytest ...` 均成功跑过；
- **全仓库源文件 CRLF**：任何替换脚本写回必须 `\r\n`，避免整文件行尾 diff；
- **PowerShell 引号**：长替换串建议写成 Python 脚本文件执行，勿用内联 here-string（转义极易出错）。

### 7.2 设计红线（勿违反）

1. 无 `--brief` 时全链路行为与旧版**逐字节一致**（注入块不渲染、门禁恒过、graph 原路径）；
2. 门禁 = **防忽略/传递完整性校验**，不是方向再评估；方向错误的反馈回路 = 前置对话修订 brief 重跑；**2026-08-20 按 C2 细化：禁止无依据 LLM 投票式方向评审，允许确定性证据（残差/量纲/边界/对照实验）反证**；
3. 优先级：**题面 > brief > 预训练直觉**；`deviated` 必须给理由；
4. **不新增图节点/边**（graph.py 唯一改动 = 条件边 `"stop": END` 映射）；
5. checkpoint/manifest 向后兼容（brief 字段默认 None、`brief_sha256` 用 `.get()`）；
6. 评审节点对 brief 只做机械覆盖 + 实现级检查（公式注意/红线），不评审方向本身（无依据 LLM 投票式；确定性证据反证除外，C2）；
7. 容量控制：brief 注入块每条 ≤200 字符、整块 ≤1500 字符级。

### 7.3 工作区安全

- 仓库含**未 commit** 修改（git `f70fc7e` 基线之上 dirty）；**禁止 `git checkout`/`git stash` 恢复**；
- **已跟踪 M（15，含 `docs/README.md`）**：`state.py`、`cli.py`、`graph.py`、`routing.py`、
  五组 prompt+node（analyst / blueprint_critic / model_critic / modeler / coder）、`prompts/writer_section.py`；
  其中 **`nodes/blueprint_critic.py` 为本轮才改**（补传 `brief=state.brief`），其余多为早前会话；
- **新建（2）**：`src/math_agent/brief.py`、`src/math_agent/brief_dialogue.py`；
- **未跟踪（??）**：本文档 `docs/10-ModelingBrief实施计划书.md`、`docs/problems/mcm51-a/brief.json`；
- **另有**：`frontend/` 四文件（brief 透传）、`tests/` 扩展与 `tests/test_brief.py` 新建；
- `.tmp_brief_edits/`：T7 已删除（曾为 apply1–8 / debug1–4 临时脚本）；
- 不修改原始题目附件，不使用 `scripts/repair_final_run.py`。

### 7.4 遗留风险与已知问题

- `brief dialogue --assist` 依赖 LLM（`STRONG_MODEL`）；未配置 LLM 时 `draft_field` 返回 None，
  交互流程会提示"起草失败"并允许人工填写/跳过（已处理，不会崩）；
- 120 passed 快照早于 cli 修复与新增测试；全量回归 **778/12/4**（见第五节）；12 失败为既有管线，未在本轮修复；
- 前端 `--brief` 透传已落地（见第五节第 2 项）；`active-run` 等环境类失败与 brief 无关时需单独处理。

---

## 八、验收标准（最终）

- 全量 `pytest` 绿（708 + 新增）——**当前未达成**（778 passed / 12 failed / 4 skipped）；`npm.cmd test -- --run` brief 透传 4 场景绿，active-run 曾因 `runs/.beacon-active.json` 指向仓外 pytest 临时目录而 403；
- `docs/problems/mcm51-a/brief.json` 八字段齐全，`math-agent brief check` 通过；
- 门禁行为有测试覆盖：缺回应 → retry → 预算耗尽 stop；全回应 → 放行；无 brief → 原逻辑；
- 无 brief 的既有测试零改动通过（向后兼容证明）；
- 六处注入有参数化测试（有 brief 含 / 无 brief 不含）；
- commit 记录 + 本文档更新为最终"已执行"状态（**当前未 commit**）。

---

## 九、体系方向声明：参考答案假设与前置/后置分工（2026-08-19 补充，跨迭代有效）

> 本节回答一个问题：建模预备（brief）在体系里**承担什么、不承担什么**。
> 防止后续迭代把本次 MCM-51 的意外条件当成通用能力，也防止把"单次跑通"当成
> 体系完善。**体系第一目标 = 以工程手段完善整个体系，而非依赖特殊输入。**

### 9.1 原则 A：参考答案不可得假设（数值注入不是通用能力）

- 本次 `docs/problems/mcm51-a/brief.json` 中的数值锚点（T_c 区间、233%、e_cr≈3.66、
  ±5% 容差、工况 A/B 参考数值等）来自**意外获得的官方参考答案**。真实使用中
  **不存在参考答案，也不存在"数值准确性范围需要注入"这类输入**。
- 因此：把参考答案数值注入 brief / 对话 / prompt 的做法**不是体系的通用能力**。
  不得写进通用路线图、不得作为建模预备的默认输入、不得作为示例模板；
  也不得用"本次能注入参考答案，所以源头方向问题已解决"来宣称 A2 目标达成。
- 与参考答案无关、**始终成立**的合法输入只有三类：**题面正文、题目自带附录数据、
  领域常识与人工方向**。
- 题目自带附录数据（数据表/附件）如何被建模预备与后置门禁**更充分地使用**，
  是与参考答案**无关**的正当研究方向（见 9.4-3）。

### 9.2 来源分级的语义（决策时点 + 信息来源，不是信任等级）

- `source` 分级描述的是"**谁在什么信息基础上做出的决策**"，不是"谁更可信"：
  - `official_standard`：官方材料（本次为意外所得，通用场景不存在）；
  - `human`：任务开始前，人基于题面 + 外部资料 + 领域经验做出的方向决策；
  - `model_draft`：任务开始后，模型仅基于题面 + 预训练直觉做出的推导。
- 已知的系统性差异：模型推导更**保守、更通用**，倾向覆盖常规要求，
  可能忽略得分导向的特殊点（高分点）；人工方向可能抓住特殊点，**也可能方向错误、
  一分不得**。两者的差异正是"决策时点与信息来源"不同造成的，不是信任等级。
- **工程决策：前置人工方向作为第一优先级**（题面 > brief > 预训练直觉）。理由：
  ① 符合体系定位——方向只在前置确定，流水线内不做无依据 LLM 投票式方向评审（设计红线；C2 已采纳后允许确定性证据反证）；
  ② 错误方向的反馈回路已经设计好——回到前置修订 brief 重跑，成本可控；
  ③ 完全依赖模型推导则任务开始前的信息全部浪费。
- 这不是"人工一定对"，而是"**谁负责方向、谁负责兜底**"的职责划分。

### 9.3 原则 B：以工程完善整个体系为第一目标（降低前置准确性要求，靠后置兜底）

- **第一目标（工程方向）**：持续**降低对前置工作（人机对话 / brief）准确性的要求**，
  把质量保证转移到后续手段（critic / consistency / 门禁 / 多轮验证 / 敏感性 /
  论文评审）上。这需要复杂方法与大量实验验证，**不承诺短期完成**，但这是体系演进的
  正确方向——因为真实场景中前置输入只能做到"方向级 + 部分实现级"，验收级数值
  锚点在无参考答案时**不存在**，只能由后置手段从题目自带数据与一致性推导重建。
- **附带收益（单次任务）**：在有参考答案的题目上，前置信息绝对足够，
  可以直接产出合格论文；但"本题接入体系后有多少可复用"必须**单独评估**，
  不得把单次成功当作体系完善，也不得反过来要求体系依赖参考答案类输入。
- 两者冲突时**优先工程目标**；单次任务的便利不得污染通用设计。

### 9.4 由此确定的边界与待办（防止混乱）

1. brief 的能力边界写死为：**方向级输入 + 实现级提示**（公式 / 参数 / 单位注意），
   **不承担**"验收级数值锚点"职责（无参考答案时该信息不存在）。
2. 验收级信息的合法来源只有：**题目自带数据 + 物理/量纲一致性 + 领域常识推导**。
   后续手段（如 validation_mapping 机器可读校验）的锚点必须从这些来源重建，
   而不是从参考答案复制。
3. 题目自带附录数据的"更充分使用"**单独立项**：建模预备的上下文注入、
   数据摘要、后置确定性校验，均以题目自带数据为合法依据。
4. 本次 brief.json 的数值条目标记为**"参考题特例"**：仅供本次单次任务使用，
   不进入通用模板 / 示例 / 路线图。

### 9.5 近期顺序（2026-08-19 共识）

- **先摸清体系、确认无隐含问题，再考虑开真跑与后续实现**：
  开 `--brief` 真跑前，先确认完整图在真实网关下的行为（既有 12 个失败是否干扰
  完整图、supervise 长跑与预算行为、recover 语义、门禁触发路径），
  不以"有参考答案所以信息足够"为理由跳过体系检查。
- 工程方向（9.3 第一目标）的探索独立推进，不阻塞单次任务，也不被单次任务绑架。

---

## 十、brief 产出路径：文档 + 提取为主，对话为兜底（2026-08-19 决定）

- **主路径（推荐）**：把已确定的方向写成文档（如迭代计划、评分标准整理），
  由 AI 从文档**提取**出符合 schema 的 brief draft（严格对齐八字段结构），
  人工**查漏补缺**（对照方向文档逐条核对：漏项、偏差、量化缺失），
  最后 `brief check` 校验后落盘。
- **兜底路径**：人脑里有方向、但没有成文文档时，用交互式对话
  （`brief dialogue --assist`，LLM 逐字段起草 + 人工确认）。本场景有现成文档，
  对话不是必要路径。
- 两条路径本质相同：**都是人确认方向**；区别只是输入形态（人脑 vs 文档）。
  对话的逐字段确认成本（token + 人工时间）远高于审一份提取 draft。
- 提取正确性由人工负责：AI 提取 draft 不是权威，必须经过人工审；
  `brief_coverage` 门禁只防"忽略"，不负责提取质量（与 9.1/9.3 一致：
  前置质量由人负责，体系只承诺传递）。
- 提取是**通用能力**：任何题目只要人有一份方向整理即可使用，不依赖参考答案
  （与原则 A 一致）。
- **命令实现状态**：`brief extract --from <doc.md> --out brief.json` **未实现**，
  本迭代只记录方向、不做命令；实现时复用 `draft_field`（起草）+ `assemble_brief`
  （组装）+ `auto_fill_ids`（id 补全）即可，成本低。
