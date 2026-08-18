# Modeling Brief：实现到哪一步、如何验证、下一步路线

- 建立日期：2026-08-19
- 关联：[实施计划书](2026-08-19-modeling-brief-plan.md)、[MCM-51 迭代计划](2026-08-18-mcm51-iteration-plan.md)、[体系流程优化报告 A2](2026-08-18-mcm51-system-evolution.md)
- 定位：**验证清单 + 下一步工作安排**。不替代计划书里的 schema/决策；只回答三件事：
  1. 信息够不够开下一轮「路线更迭」；
  2. 目标句现在实现到哪一层；
  3. 接手者按什么顺序验证、验证通过后才改 coder/modeler。
- 工作区：HEAD `f70fc7e`，brief 全栈**未 commit**；全量 pytest **778 passed / 12 failed / 4 skipped**（12 失败为既有管线，非 `test_brief.py`）。

---

## 一、目标句拆开对照（现在做到哪）

目标原文：

> 任务开始前，由人 + AI 对话产出 `brief.json`（八字段：逐题方向/公式注意/讨论点/红线/图表/评分/数据注意/文献方向），注入流水线，在源头杜绝方向性错误。

| 子句 | 代码/产物现状 | 是否已用真题跑通 | 结论 |
|---|---|---|---|
| 任务开始前 | CLI `brief init/check/dialogue` 在主图之外；`run/supervise --brief` 启动时写入 `state.brief` | 未做带 `--brief` 的正式 run | **管道就绪，未实跑** |
| 人 + AI 对话产出 | CLI `brief dialogue --assist`：每字段 LLM 起草 + 人工确认；失败可手填 | **从未**用 MCM-51 走完一轮对话 | **能力有，无使用证据** |
| 八字段 `brief.json` | `ModelingBrief` schema + `docs/problems/mcm51-a/brief.json`（39 条 id，`brief check` [OK]） | 文件由人按迭代计划填写，不是对话产物 | **内容有，来源不是对话** |
| 注入流水线 | 六处：analyst / blueprint_critic / model_critic / modeler / coder / writer_section；`run_manifest.brief_sha256`；`out/brief.json` 副本 | 仅单测 mock prompt 含块 | **接线已测，流水线未测** |
| 在源头杜绝方向性错误 | `brief_coverage` 只校验「analyst 是否逐条回应」，**不评判方向对错**；方向错了只能改 brief 重跑 | 无论文/代码对照 1.2 变点检测等 | **防忽略 ≠ 防方向错；后者未验证** |
| Web 对话 | 本迭代明确只做文件透传（`briefPath` → `--brief`） | 无对话 UI | **按决策后置** |

一句话：**A2 的「管道」已经接到图上；A2 的「效果」（源头不再犯 1.2/3.1/3.2/4 方向错）一次都还没在真实流水线上证明。**

分层认知仍成立，不要把下一轮做成「再评估 brief 对不对」：

- 方向级：前置对话 / 现成 `brief.json`；
- 实现级：现有 critic / consistency / runner 门禁；
- 传递级：`brief_coverage` 硬停（已实现、有单测）。

---

## 二、信息是否足够开「路线更迭」

**够用来写代码转向清单，不够用来宣称体系已完善。**

已经足够、不必再调研就能动手的：

- 方向对不对：见 [iteration-plan](2026-08-18-mcm51-iteration-plan.md) 第三、四节（变点检测、F_bond 钻孔直径、调心垫圈 233%、偏心压陷、围岩分级）。
- 注入什么约束：见 `docs/problems/mcm51-a/brief.json` 的 39 个稳定 id。
- 流水线怎么吃 brief：见计划书第三、四节 + 本仓库未提交的 `brief.py` / 六处 prompt。

还必须补证据、否则「路线更迭」会和 r11 一样盲改：

- **没有**带 `--brief` 的 MCM-51 新 run（analyst 的 `brief_coverage`、coder 是否避开红线、论文是否出现 3.1-e0 讨论，全无 runs 产物）。
- **没有**把对话走通：不知道 `--assist` 在本机网关/模型下是否可用、耗时、人要改多少。
- 全量 12 失败（coder 多图、granular recovery、graph smoke 不出 paper）与 brief 无关，但会干扰「跑一遍完整图」的信心；**另案**，不要和 brief 绑在一起修。

建议顺序：**先验证管道（第三节）→ 再开一条带 brief 的 MCM-51 短跑 → 用第四节清单判定方向是否被执行 → 最后才改 coder/modeler 实现。** 不要在未验证注入的情况下直接大改求解代码。

---

## 三、如何验证「管道」——不联网 / 低成本（应先做）

工作目录：`E:\git_clone\Beacon`。Python 用 `.venv\Scripts\python.exe`，不要 `uv run`（本机 uv cache 常无权限）。

### 3.1 模块能 import、brief 合法

```powershell
.venv\Scripts\python.exe -m py_compile src\math_agent\cli.py src\math_agent\brief.py
.venv\Scripts\python.exe -m math_agent.cli brief --help
.venv\Scripts\python.exe -m math_agent.cli brief check --brief docs\problems\mcm51-a\brief.json
.venv\Scripts\python.exe -m pytest tests\test_brief.py tests\test_routing.py tests\nodes\test_analyst.py tests\nodes\test_blueprint_critic.py tests\test_cli.py -q
```

通过标准：`brief check` 输出 `[OK]` 且「共 39 条待回应条目」；上述 pytest 全绿（T4 曾 131 passed 子集）。

### 3.2 无 brief 时行为不变（向后兼容）

不传 `--brief` 启动（或看单测：routing 原 4 条零改动）。门禁 `brief_coverage_problems(None, …) == []`。

### 3.3 CLI 对话（可选、要 LLM）

```powershell
.venv\Scripts\python.exe -m math_agent.cli brief dialogue --problem <题面 spec.json> --out docs\problems\mcm51-a\brief-from-dialogue.json --assist
```

通过标准：能逐字段出草稿或提示起草失败后手填；落盘后再 `brief check`。  
**失败不算 A2 管道失败**（无密钥/网关时 `draft_field` 返回 None 是设计）。失败则继续用已有 `docs/problems/mcm51-a/brief.json`。

### 3.4 Web 透传（不要求对话 UI）

高级选项填 `docs/problems/mcm51-a/brief.json`，启动后 `run.log` / `run.command` 含 `--brief` 与经 `safeProjectPath` 的路径。  
`npm.cmd test -- --run`：brief 四场景应绿；若 `GET /api/active-run` 403，先看 `runs/.beacon-active.json` 是否指向仓外 pytest 临时目录（环境脏，与 brief 无关）。

---

## 四、如何验证「源头杜绝方向错」——必须有一次真跑（下一步核心）

管道绿 **不能** 代替这一节。`brief_coverage=followed` 只说明 analyst **声称**跟了 brief，不说明代码做了变点检测。

### 4.1 建议的最小真跑

新目录，禁止 recover 旧 `51mcm-a-*`：

```text
math-agent supervise --problem <MCM-51 spec> --out runs/51mcm-a-brief-v1 --brief docs/problems/mcm51-a/brief.json --thread default
```

（Web 等价：同一 `--out` + 高级选项 brief 路径。）

跑到至少 **blueprint_critic 之后**（更好：穿过 coder 首轮 execute）。不必一次出 PDF。

### 4.2 产物核对清单（有文件才算数）

| 检查项 | 看哪里 | 通过 |
|---|---|---|
| brief 进了这次 run | `runs/51mcm-a-brief-v1/brief.json` 与源文件一致；`run_manifest.json` 有 `brief_sha256` | 有副本、hash 对得上 |
| 状态带 brief | checkpoint / `state_summary` / insights 中 analyst 输入含「人工建模预备」 | prompt 不是空注入 |
| 传递完整性 | `problem_blueprint.brief_coverage` 覆盖全部 39 个 id；`followed` 或 `deviated`+非空 reason | 缺一条会 retry，预算尽则 **stop**（不是带病进 modeler） |
| 方向是否落地（抽样） | 蓝图/模型/代码/论文是否出现：1.2 分段回归；F_bond 用钻孔直径；3.1 调心垫圈/e=0/233%；禁止 600.71 硬编码；禁止 `T_opt=0.8·T_max` | **人工抽 5 条红线+方向**；未出现 = 管道通、效果未通 |
| writer 讨论点 | `paper.md` 对应章节是否含 `3.1-e0` 等 required_discussions | 按 `sections` 白名单 |

### 4.3 判定语言（避免把「接到了」说成「杜绝了」）

- **管道成立**：4.2 前三行通过。
- **防忽略成立**：coverage 缺项会停，不会默默丢掉 brief。
- **源头杜绝方向错成立**：4.2 抽样方向在 **代码与论文** 中可指认（对照 iteration-plan 空白 40 分项）。这一条在本文撰写时 **尚未有 runs 证据**。

若管道成立但方向未落地：先改 prompt 注入容量/措辞或收紧 coder 红线提示，再考虑改求解实现；不要先加「方向再评估」图节点（计划书红线）。

---

## 五、下一步工作安排（按序）

1. **提交 brief 全栈**（需你明确说 commit）：冻结管道，避免下一轮和未提交 diff 缠在一起。12 个既有失败不要塞进这次 commit。
2. **第三节低成本验证**（本机 10 分钟）：check + 相关 pytest；可选 `brief dialogue`。
3. **第四节真跑 `51mcm-a-brief-v1`**：停在蓝图后也可先出 coverage 报告，再决定是否烧 coder 预算。
4. **按抽样结果分支**：
   - coverage 都 followed 但 1.2 仍走力学 min → 注入未改变决策，改 analyst/modeler prompt 或 brief 措辞，重跑；
     （恢复语义提醒：**修 prompt（代码）可 `recover` 续跑（沿用 checkpoint 内旧 brief）；修 brief 只能全新 `run`**
     （新 `--out` 或 `--force`）；`recover`/`supervise-resume`/`supervise-recover` 均不接受 `--brief`；
     门禁 `stop` 后 checkpoint `next=()`，`recover` 为空转）
   - coverage 反复 stop → analyst 吃不下 39 条，做容量（每条 ≤200 字、整块 ≤1500）或拆 brief；
   - 方向已写进蓝图但 coder 仍错 F_bond → 进入 iteration-plan 的代码转向（实现级），此时信息才够改求解器。
5. **后置（本迭代不做）**：Web 对话式建模预备 UI；把 brief 做成方向再评估；并行蓝图 / RAG 资料包（A2 以外方案）。

路线更迭的「代码改什么」仍以 [iteration-plan 第四节](2026-08-18-mcm51-iteration-plan.md) 为准；**启动条件**是第四节至少有一次带 brief 的蓝图/coder 证据。

---

## 六、接手者开场四件事

1. 读 [modeling-brief-plan.md](2026-08-19-modeling-brief-plan.md) 第二、三节（决策与 schema），再读本文第三、四节（怎么验）。
2. 仓库仍可能 dirty；**禁止 `git checkout` 恢复** brief 相关文件。
3. 不要把 12 个全量失败当成 brief 回滚信号。
4. 没有 `runs/*/brief.json` + coverage 抽样前，不要写「已在源头杜绝方向性错误」。
