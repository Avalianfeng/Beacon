# Beacon 设计债与遗留问题清单

- 建立日期：2026-08-19（延续 P01–P20 问题清单模式：`docs/2026-08-18-mcm51-issue-report.md`）
- 定位：**在直接接触底层代码过程中发现的问题与决策，逐条登记；解决后逐个标注"已解决"**。
  防止问题被遗忘、被后续迭代重复踩坑。不与任何单次任务绑定，跨迭代有效。
- 状态约定：`待处理` / `处理中` / `已解决` / `已决策`（确认不改代码，记录理由）/ `另案`（与当前主线解耦）/ `规划中`（已定路线未动工）。

---

## 一、brief 链路相关（2026-08-19 排查产出）

| # | 问题 | 位置 | 状态 | 备注 |
|---|---|---|---|---|
| B01 | checkpoint 反序列化 allowlist 缺 `ModelingBrief`/`BriefCoverageItem`（定义在 `math_agent.brief`，不在 `_allowed_state_types()` 收集范围内）→ 每次读含 brief 的 checkpoint 打 "Blocked deserialization" 警告；开 `LANGGRAPH_STRICT_MSGPACK=true` 会硬失败 | `src/math_agent/checkpointing.py:16-27` | 已解决（2026-08-19） | allowlist 已收集 math_agent.brief 类型；tests/test_checkpointing.py 新增 2 测试（往返无警告、类型正确） |
| B02 | `out/brief.json` 副本与 `run_manifest.brief_sha256` 零测试覆盖（只测到 args 拼装/错误路径；副本与 manifest 只由 worker 子进程写 `cli.py:586-588`） | `tests/test_cli.py` | 已解决（2026-08-19） | tests/test_cli.py 新增 3 测试（纯函数往返、同路径早退、invoke 前落盘） |
| B03 | `supervise`（`cli.py:988`）与 `start`（`cli.py:1046`）各自计算 `brief_sha256` 但从不使用（死代码，易误导"主进程已写 manifest"） | `src/math_agent/cli.py` | 已解决（2026-08-19） | supervise/start 死计算已删；残留 `brief_sha256 = None` 初始化行（无害死名，低优先清理） |
| B04 | `_warn_brief_problem_mismatch`（计划书承诺"problem_id 与题目不匹配仅警告"）定义后从未被调用，承诺不生效 | `src/math_agent/cli.py:385` | 已解决（2026-08-19） | 三处接线；不匹配 → stderr [WARN]，problem_id 空/匹配静默 |
| B05 | `recover`/`supervise-resume`/`supervise-recover` 均不接受 `--brief`；门禁 stop 后 checkpoint `next=()`，recover 是 no-op（打印 recovered 但不重跑）；**修 brief 只能全新 run**（新 `--out` 或 `--force`） | `src/math_agent/cli.py:819/1176/1217` | 已决策（不改代码） | 文档已修正语义（计划书决策表 #1、验证文档）；修 prompt 可 recover 续跑（沿用 checkpoint 内旧 brief） |
| B06 | 注入契合度缺口：图表规划/评分要点/数据注意/文献方向四个字段**无直接注入点**，只在 analyst/blueprint_critic 全量块出现一次，后续节点依赖 analyst 转述（信息衰减）；figure/paper_critic/evaluation 环节无 brief 注入 | `src/math_agent/brief.py` 渲染器 + `prompts/*` | 规划中 | 计划文档已写：[`2026-08-19-injection-plan.md`](2026-08-19-injection-plan.md)；**执行顺序：先真跑抽样判定 → 阶段 1 纯 prompt 接线 → 阶段 2 结构化传递（依效果决定）** |
| B07 | checkpoint 往返中 brief 序列化降级（state.brief 存为 dict，恢复时靠 pydantic 重校验回 ModelingBrief） | `checkpointing.py` / `state.py` | 已决策（接受） | 探针实测恢复后类型正确、门禁可再判；B01 修复后无警告 |
| B08 | `brief extract`（方向文档 → AI 提取 draft → 人工查漏补缺 → check）命令缺失；对话（`--assist`）仅为兜底路径 | `src/math_agent/cli.py` | 已决策（本迭代不实现） | 产出路径方向已记录（计划书第十节）：文档+提取为主、对话兜底；命令实现后续评估 |
| B09 | brief_coverage 完整路径（analyst 缺回应→retry→analyst 重跑→再缺→stop→END）无图级集成测试；门禁 stop 后的 run 目录产物与 recover 空转行为无测试 | `tests/test_routing.py` / `graph.py:150` | 待处理 | 低优先；现有覆盖：routing 纯函数档位 + 节点迭代递增 + stop 映射（无测试锚点） |
| B10 | coder 生成期节点内吞错重试（把 `LLMConnectionError` 等异常当"代码被截断"反馈喂回 LLM，上限 2 次）改变"崩溃→checkpoint→recover"语义；502 期间预算消耗更大 | `src/math_agent/nodes/coder.py:2799-2821` | 已记录（待评估） | 与 B 类 12 个失败同源；是否改回"异常传播"需评估预算 vs 恢复语义 |

## 二、既有测试欠账（另案，不与 brief 绑定）

| # | 问题 | 位置 | 状态 | 备注 |
|---|---|---|---|---|
| B11 | 12 个既有失败全部为测试断言过期/环境配置，非 brief 链路：A) coder 相关 7 个（figure 必须产 PNG 门禁 `coder.py:2909-2920` + 节点内重试 + sensitivity schema 变化）；B) 端到端 4 个（mock 代码不产 PNG → 无主证据 6 批硬停 → 到不了 writer）；C) finalizer 1 个（本机 `.env` 20 页/15000 vs 测试 12/10000） | 见全量 pytest 输出 | 另案 | 其中端到端 4 个意味着：**现有测试无法端到端验证"图能写出 paper.md"**，带 brief 真跑是首次真实端到端验证，coder 段风险在真跑中首次真实暴露 |
| B12 | `runs/.beacon-active.json` 被 pytest 的 supervise 测试写入并指向测试临时目录（环境脏；Web `/api/active-run` 403 的已知成因） | `runs/.beacon-active.json` | 已记录 | 真跑/下次 supervise 会自行覆盖；清理需人工确认 |

## 三、环境与文档

| # | 问题 | 位置 | 状态 | 备注 |
|---|---|---|---|---|
| B13 | `docs/README.md` 物理行尾为 `\r\r\n`（历史工具双重转换遗留；read 工具归一化显示无碍，Python 按字面读出现双空行） | `docs/README.md` | 待处理 | 低优先；统一清理行尾时一并处理，git diff 可读性 |
| B14 | 计划书第九节「体系方向声明」（参考答案不可得假设 / 来源分级语义 / 以工程完善体系为第一目标 / 近期顺序） | `docs/2026-08-19-modeling-brief-plan.md` | 已解决 | 2026-08-19 落地 |

---

## 使用约定

- 新发现的问题随手登记（编号顺延 B15…），解决后在"状态"列改为 `已解决` 并注明日期，不改历史行。
- 与单次任务绑定的问题不进本清单（进对应任务文档）；跨迭代、与具体题目无关的问题进本清单。
