# Beacon 文档中心

> **核心原则**：文档以「**优化整个体系**」为核心组织；单题任务与历史文档一律归档于
> `archive/`，不再维护。先读事实源（00），再按需深入。

## 一、现在在哪 → 先读这个

- **[`00-体系现状与原则.md`](00-体系现状与原则.md)**：体系事实源（持续更新）——我们在做什么、八条核心原则、当前状态与关键数字、待办池、下一步阶段、中长远路线图、给智慧中枢的输入清单。

## 二、体系怎么工作（实现契约）

- [`01-论文内容质量与篇幅门禁.md`](01-论文内容质量与篇幅门禁.md)：论文证据、深度实验、图文排布和篇幅门禁。
- [`02-长流程可靠执行与恢复.md`](02-长流程可靠执行与恢复.md)：后台监督、恢复、硬期限和最终原子收口。
- [`03-控制台观察面.md`](03-控制台观察面.md)：观察面（`watch` / `progress.jsonl` / `insights/`）。
- [`11-ModelingBrief流程总图.md`](11-ModelingBrief流程总图.md)：全流程总图（前置对话 → 注入 → 门禁 → 主图）。

## 三、当前工作载体（Modeling Brief 系列）

- [`10-ModelingBrief实施计划书.md`](10-ModelingBrief实施计划书.md)：brief 设计（schema/注入/门禁）+ 第九节方向声明 + 第十节产出路径。
- [`12-ModelingBrief验证与下一步.md`](12-ModelingBrief验证与下一步.md)：验证清单 + **第七节 brief-v1 评审结论** + **第八节机制修复清单（M1–M6）**。
- [`13-注入体系补全计划.md`](13-注入体系补全计划.md)：八字段 × 节点注入矩阵、转述衰减缺口、阶段化补全、不走 RAG 决策。
- [`14-设计债与遗留问题清单.md`](14-设计债与遗留问题清单.md)：B01–B25（B21–B25 为智慧中枢评估新增；已解决/已决策/规划中/待处理/另案）。
- [`15-智慧中枢评估与处置.md`](15-智慧中枢评估与处置.md)：外部独立评估要点 + 逐条处置（H01–H20）+ 原则修订（C1–C4 已采纳，2026-08-20）。
- [`16-中长远路线图.md`](16-中长远路线图.md)：战略三选项 + 门控阈值 + 阶段 0–4 + Go/No-Go 与投入护栏。
- [`17-资料补全清单.md`](17-资料补全清单.md)：智慧中枢建议补充的 11 项证据采购跟踪。
- [`brief-playbook.md`](brief-playbook.md)：**brief 生产手册（方向生产协议，2026-08-21，最高杠杆资产）**——开放探索 → 多视角对撞 → 逐问清点 → 方向收敛 → brief + 提示词包 + pilot/评估简报模板。
- [`实现计划-8-20/`](实现计划-8-20/README.md)：执行层落地批次（**v2 主线（2026-08-21）：brief-playbook → 导入最小闭环 → M3 → M2 → pilot → mcm51-b 干净题真跑**；批次 0 已完成；M4/批次 4/前端完整形态冻结，A 题 brief-v2 降级可选；07 待决策指针；10 前端+Web 入库另案）。
- `problems/mcm51-a/brief.json`：MCM-51 方向约束（40 条，M6 增 1.2-reg-coef；当前参考题特例）。

## 四、历史归档（不再维护，链接可能失效，以本索引为准）

- [`archive/单题任务/`](archive/单题任务/)：04 华中杯质量差距、05–09 MCM-51 系列（问题汇报 P01–P20 / 迭代交接 / 论文成果 / 整改迭代计划 / 体系流程优化报告）。
- [`archive/历史设计/`](archive/历史设计/)：15 全流程故障根因、16 LLM 超时重试、17 ProblemBlueprint 方案、18 Writer 质量改造、superpowers 阶段性计划与规格。

## 五、验证入口

```powershell
.venv\Scripts\python.exe -m pytest -q            # 全量基线 810 passed / 0 failed / 4 skipped（收集 814；12 失败已清零，2026-08-20 修复入库 9f2906c）
npm.cmd test -- --run                            # Web 测试
.venv\Scripts\python.exe -m math_agent.cli status --out runs/<run> --thread <thread>
.venv\Scripts\python.exe scripts\sample_brief_direction.py runs\<run> --brief-source docs\problems\mcm51-a\brief.json
```

> 论文运行验收：`completion.json` 哈希、正式证据角色、LaTeX 日志零错误；**.md 为主交付物**（PDF 仅预览/编译链路验证，不承诺完整可交付；格式调整走人工后续流程，2026-08-20 定位）。
