# Beacon 项目状态窗（PROJECT STATUS）

- 建立日期：2026-08-19
- 定位：**整个项目"哪个文件夹/文件是干什么的"一览**，重点标注最新改动；帮助快速掌控全局状态。
  复杂代码只讲模块职责（包裹式），细节看 `docs/README.md`（文档索引）与各模块源码。
- 技术栈：Python（核心引擎，src/math_agent/）+ Node（Web 前端，frontend/）+ SQLite（checkpoint/RAG 库）。

---

## 一、当前状态速览（2026-08-19）

| 项 | 状态 |
|---|---|
| brief 全栈（建模预备） | ✅ 已落地并 commit：`3e97a20`（实现）、`1177328`（测试）、`75fa0b2`（Web 透传）、`f2a263c`（文档） |
| 第一次带 brief 真跑 | `runs/51mcm-a-brief-v1`：跑通到 human_review → 批准 → **degraded**（LaTeX 编译失败 / 论文评审 7 分 < 9 / 对照方案 0 个）；**coverage 39/39 全 followed**；方向抽样显示 1.2 变点 / 2.2 钻孔直径 / 3.1 调心垫圈 / 4 分级已落地，两条红线（600.71、0.8·T_max）零触碰 |
| 对照官方评分标准的论文评审 | 进行中（子 agent 按唯一官方材料《评分参考标准》逐题评估 brief 效果） |
| 12 个既有测试失败 | 另案（与 brief 无关，见设计债 B11） |

## 二、顶层目录职责

| 路径 | 职责 |
|---|---|
| `src/math_agent/` | **核心引擎**（见下节模块清单） |
| `tests/` | 测试。重点：`test_brief.py`（brief 全链路单测）、`test_checkpointing.py`（checkpoint allowlist + 往返）、`test_cli.py`（含落盘副本/hash 断言） |
| `frontend/` | Web UI（Node）。`server.mjs` 负责启动参数拼装（含 briefPath → `--brief` 透传）；**对话式建模预备 UI 明确后置** |
| `docs/` | 文档。入口 `docs/README.md`（索引）。`docs/problems/mcm51-a/brief.json` = MCM-51 方向约束（39 条） |
| `runs/` | 运行产物。`51mcm-a-brief-v1`（最新真跑）、`51mcm-a-sens-scan-r11`（上一轮基线）、`ui-test-*`（Web 测试残留）、`rag.sqlite`（不存在——RAG 未启用） |
| `corpus/models/` | 建模方法资料（md 心得 + 算法书 PDF 集）。**沉睡语料**：代码零引用，RAG 决策后不投入使用（设计债 B15） |
| `problems/` | 题面 spec JSON（如 `huazhong-2026-a-green-logistics.json`） |
| `scripts/` | 工具脚本。`sample_brief_direction.py`：对 run 产物做方向/红线抽样 + coverage 统计（只读） |
| `.env` / `.env.example` | 环境配置：模型路由（`openai/<model>`）、密钥、RAG 开关（=0）、篇幅阈值（20 页/15000 字）、门禁阈值 |

## 三、核心引擎模块清单（src/math_agent/）

| 模块 | 职责（包裹式） |
|---|---|
| `state.py` | **全流水线的数据契约**：所有节点读写的巨型 JSON 结构（MathModelingState），含 brief 字段与 ProblemBlueprint.brief_coverage |
| `brief.py` | **建模预备（新）**：brief 八字段 schema + 五个 prompt 渲染器（full/modeler/coder/critic/discussions）+ `brief_coverage_problems` 门禁纯函数（防忽略，不评方向） |
| `brief_dialogue.py` | **brief 对话起草（新）**：LLM 逐字段起草 + 人工确认；草稿按字段类型清洗（reference_direction 字符串化） |
| `cli.py` | 命令入口：`run` / `supervise` / `start` / `recover` / `resume` / `brief init\|check\|dialogue` / `ingest` / `status` 等。含 `--brief` 校验、落盘副本（out/brief.json）、manifest brief_sha256、problem_id 不匹配警告 |
| `graph.py` | 流水线图：节点连接与条件边（blueprint_critic 的 retry/advance/stop→END；human_review interrupt） |
| `routing.py` | 节点间路由：`after_blueprint_critic` 接 brief 门禁（缺回应→retry≤2→stop）；无主证据预算硬停等 |
| `checkpointing.py` | checkpoint 序列化：SQLite + msgpack + **类型白名单**（state/brief 两模块；2026-08-19 修复 brief 类型缺失） |
| `supervisor.py` | 后台监督进程：启动 worker、崩溃自动恢复、硬期限、写 supervisor.json |
| `llm.py` | LLM 调用封装：超时/重试/结构化输出（pydantic schema）/降级路由 |
| `config.py` | 阈值与开关：MIN_MODEL_CODE_SCORE=8、MIN_PAPER_CRITIC_SCORE=9、MAX_BLUEPRINT_ITERATIONS=2、RAG_*、篇幅阈值 |
| `nodes/` | 流水线各节点：analyst（读题出蓝图）→ blueprint_critic（审蓝图）→ modeler（写模型）→ model_critic → coder（写代码）→ model_code_consistency（模型-代码对账）→ sensitivity → figure → writer → paper_critic → evaluation → human_review → latex → finalizer |
| `prompts/` | 各节点提示词模板；**六处已接 brief 注入**：analyst / blueprint_critic（全量块）、modeler（方向+公式）、model_critic / coder（公式+红线）、writer_section（讨论点按分组过滤） |
| `rag/` | RAG 五件套（chunking/embeddings/store/retrieve/ingest）。**已决策不启用**（设计债 B15）：embedding 网关不支持 + 通用知识前置覆盖 |
| `runner/` | 代码执行沙箱：120s/2GB 硬限制、拒绝硬编码/全零/非法数值/退出码 0 的失败声明/未读附件 |

## 四、最新改动重点（2026-08-19 会话，均已 commit）

1. **brief 全栈**：schema（39 条 id）+ 六处注入 + coverage 门禁（retry→stop）+ CLI 命令组 + Web 透传 + 落盘副本/hash。
2. **checkpoint allowlist 修复**：`ModelingBrief`/`BriefCoverageItem` 入白名单（消除 "Blocked deserialization" 警告与严格模式硬失败风险）。
3. **落盘链路补测 + 死代码清理**：副本/hash 测试（纯函数 + CliRunner 早期路径）；supervise/start 死 hash 删除；problem_id 不匹配警告接线（真跑实测对正确 brief 误报，匹配需规范化——设计债 B04）。
4. **文档五篇 + README 索引**：计划书（含第九节方向声明、第十节产出路径）、验证清单、流程总图、注入补全计划（第六节：不走 RAG）、设计债清单（B01–B15）。
5. **真跑证据**：`runs/51mcm-a-brief-v1`（详见第一节；评审报告待出）。

## 五、运行须知

- Python 用 `.venv\Scripts\python.exe`（不要 `uv run`，uv cache 无权限）；PowerShell 直调 python 偶发"拒绝访问"，用 `cmd /c` 包裹。
- 全量测试基线：**787 passed / 12 failed / 4 skipped**（12 个失败为既有管线，另案）。
- 仓库行尾：源文件 CRLF；新写 md 用 LF 即可（git autocrlf 统一）。
- 硬性约定：模型名必须 `openai/<model>`；不修改原始题目附件；不用 `scripts/repair_final_run.py`；无 runs 证据不宣称"已在源头杜绝方向性错误"。
- **论文交付形态（2026-08-19 确认）**：以导出的 `.md` 为主交付物（后续接入 `D:\数学建模`，md → word 调格式，自由度更高）；**PDF 态度：能用就行，不追求排版质量**。
