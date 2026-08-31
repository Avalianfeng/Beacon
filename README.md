<p align="center">
  <img src="frontend/assets/beacon-logo.png" alt="Beacon Logo" width="180" />
</p>

<h1 align="center">Beacon</h1>
<h3 align="center">竞赛建模的方向执行与论文生产平台</h3>
<p align="center"><em>本仓是 <a href="https://github.com/123-qw-as/Beacon">123-qw-as/Beacon</a> 的 fork，不是上游的一键出论文产品。</em></p>

<p align="center">
  <a href="#这是什么"><strong>这是什么</strong></a> ·
  <a href="#相对上游改了什么"><strong>相对上游</strong></a> ·
  <a href="#快速开始"><strong>快速开始</strong></a> ·
  <a href="#默认做题路径-s0s8"><strong>做题路径</strong></a> ·
  <a href="#可选-s9-流水线与-web-ui"><strong>S9 / Web</strong></a> ·
  <a href="#文档"><strong>文档</strong></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11–3.13-blue" alt="Python 3.11–3.13" />
  <img src="https://img.shields.io/badge/node-≥18-green" alt="Node 18+" />
  <img src="https://img.shields.io/badge/framework-LangGraph-orange" alt="LangGraph" />
  <img src="https://img.shields.io/badge/llm-LiteLLM-purple" alt="LiteLLM" />
</p>

---

## 这是什么

Beacon 帮数学建模竞赛队伍走完「从题面到可溯源论文」这条路。它**不承诺无人值守出好论文**。

本 fork 的定位是**专家副驾驶**（人 + 外部强模型先定方向，体系忠实执行并机械校验）：

1. **方向在流水线外生产**：按 [brief-playbook](docs/brief-playbook.md) 做探索、对撞、清点，再写成 `brief.json`。
2. **默认路径是分阶段操作面 S0–S8**：人 / 外部 agent 按阶段导入、探查、求解、登记、装配、评审、放行。
3. **LangGraph 14 阶段图是可选工具（S9）**：`start` / `supervise` 不作主路径；无冻结代码时 **coder LLM 默认关闭**。
4. **交付物以 `paper.md` 为主**：PDF 只做编译链路验证，不承诺可直接提交。

完整端到端图（Beacon 生产 ↔ 工作面后处理 ↔ 赛后回流）见 [内外全流程总纲](docs/内外全流程总纲.md)。

---

## 相对上游改了什么

上游（[123-qw-as/Beacon](https://github.com/123-qw-as/Beacon)）把 **Web UI + 完整 LangGraph 流水线**写成主产品：粘贴题面 → 自动分析 / 建模 / 写码 / 作图 / 写论文 / 出 PDF。本 fork 保留这条图，但把它降为工具层，并拆掉题域特化。

| 维度 | 上游 | 本 fork |
|------|------|---------|
| 主路径 | 一键跑 14 阶段图 | 人 / agent 分阶段 S0–S8；S9 可选 |
| 方向从哪来 | 图内 Analyst 拆题 | 图外 brief（探索 → 对撞 → 清点 → `brief.json`） |
| 求解代码 | coder 默认 LLM 生成 | 默认走冻结资产（T-19）或 `source/inject/`；LLM 须 `--allow-coder-llm` |
| 失败策略 | critic 循环、分数不够再试 | 四门禁**首次未过即停**；接续用 `review` / `restart --from coder` |
| 质量兜底 | 节点评分 + HITL | 机械闸门：数字溯源、L4、红线、claims、`brief_sha256` |
| 题域 | 曾含城市绿色物流专用求解器 / 离线契约 | **已拆除**（2026-08-21）；只留通用闸门 + 题级 brief |
| RAG | 可选向量检索 | 当前**不启用**（embedding 网关不支持；改文本资料包前置注入） |
| 终稿 | 强调 PDF | **`.md` 为主**；PDF 仅预览 |
| 论文谁产 | 流水线 writer | Beacon 仍产完整论文本体；外部工作面只做拆开 / Word / 赛后评估 |

本仓还加了上游没有的操作面命令：`problem import/show/stage`、`brief init/check`、`reference add/run/tables/paper/expand/verify/recertify`、`review-check`、`accept`，以及 `pause` / `restart`。

决策与证据入口：[00-体系现状与原则](docs/00-体系现状与原则.md)、[07 决策登记](docs/实现计划-8-20/07-待决策与超范围.md)（D-002 / D-005 / D-020～D-027）。

---

## 快速开始

### 环境

- Python 3.11–3.13、[uv](https://docs.astral.sh/uv/getting-started/installation/)、Node.js ≥ 18
- OpenAI 兼容的 LLM 端点（本机网关或云厂商）

```bash
git clone https://github.com/Avalianfeng/Beacon.git
cd Beacon
uv sync
copy .env.example .env   # Unix: cp .env.example .env
```

编辑 `.env`：至少填 `OPENAI_API_BASE`、`OPENAI_API_KEY`，模型名必须是 `openai/<model>`。完整旋钮以 `.env.example` 为准。

第一次确认安装：

```bash
uv run math-agent --help
```

应看到 **S0–S8 做题主路径**，S9 写在「可选遗留执行器」段。已有范本可直接看阶段：

```bash
uv run math-agent problem stage mcm51-c --json
```

只跑 Web 工作台时再 `npm install` 与 `npm start`（见下文「S9 / Web UI」）。CLI 不依赖前端。

---

## 默认做题路径（S0–S8）

命令前缀：`uv run math-agent` 或 `.venv\Scripts\python.exe -m math_agent.cli`。

```text
赛题 ─► S0 导入 ─► S1 数据探查 ─► S2 探索 ─► S3 brief
              ─► S4 预检 ─► S5 求解验证 ─► S6 登记装配
              ─► S7 评审 ─► S8 人审放行 ──► paper.md
                    │
                    └── S9 流水线（可选，不作主路径）
```

| 阶段 | 做什么 | 命令 / 产物 |
|------|--------|-------------|
| S0 | 归档题面与附件（哈希，无 AI 起草） | `problem import` / `show` / `stage` |
| S1 | 数据探查 + 每附件概览图 | 写 `data_profile.md`（无 CLI） |
| S2 | 探索、对撞、清点、领域知识 | 写 `exploration.md` / `领域知识.md`（协议见 playbook） |
| S3 | 方向收敛 | `brief init` · `brief check` |
| S4 | 预检 | `run --dry-run` → `preflight.json` |
| S5 | 独立复核求解证据 | `reference verify` · `reference recertify` |
| S6 | 登记参考实现 → 跑数 → 表 → 骨架 → prose | `reference add/run/tables/paper/expand` |
| S7 | 机械评审（数字 / L4 / 红线 / claims） | `review-check` |
| S8 | 人审登记 | `accept --approve` / `--no-approve` |

`problem stage <题号> --json` 会给出已完成前缀、`next_command` 和人检缺口 `d007_missing`。细则：[操作面契约](docs/实现计划-8-20/8-27-操作面契约.md)。新题开工先读 [brief-playbook](docs/brief-playbook.md)。

方向错了回 S3 改 brief，不在图内做 LLM 投票。无 T-19 冻结资产、又没有 `problems/<题>/source/inject/` 时，不要对 S9 抱「自动写码」的期望。

---

## 可选：S9 流水线与 Web UI

LangGraph 仍在：分析 → 蓝图评审 → 建模 → 编码 → 一致性 → 敏感性 → 作图 → 写作 → 论文评审 → 评估 → 人审 → LaTeX。本 fork 里它是**可选执行器**。

```bash
# 无冻结代码时必须显式允许 LLM 写码，否则 coder 立即停
uv run math-agent start \
  --problem problems/<题>/problem.json \
  --brief problems/<题>/brief.json \
  --out runs/<run> \
  --allow-coder-llm

uv run math-agent watch --out runs/<run>
uv run math-agent status --out runs/<run>
```

门禁首次未过会 `stop`（不是带病前进）。接续：

```bash
uv run math-agent restart --out runs/<run> --from coder
uv run math-agent recover --out runs/<run>
uv run math-agent review --out runs/<run>    # 流水线人审接管；勿与 review-check 混用
```

`supervise` / `pause` / `supervise-resume` 仍可用，只是**不是默认竞赛路径**。

Web UI（`npm start` → http://localhost:5173）驱动的是这条 S9 图：导入题面、看进度、从 checkpoint 恢复。它**不会**替你走 S0–S8 的 brief / reference / review-check。首次打开仍会引导写 `.env`。说明见 [frontend/README.md](frontend/README.md)。

---

## 项目结构（做题时看这些）

```
Beacon/
├── problems/<题号>/          # 题目档案（导入后的事实源）
│   ├── source/               # 题面+附件（哈希冻结）
│   ├── source/reference/     # S6 登记的参考实现
│   ├── source/inject/        # 无哈希交代码（S9 可选）
│   ├── problem.json          # spec
│   └── brief.json            # 方向约束
├── src/math_agent/           # CLI、graph、nodes、闸门
├── scripts/                  # check_paper_numbers / check_l4_gates / …
├── docs/                     # 现行文档中心（先读 docs/README.md）
├── frontend/                 # 可选 Web 工作台
└── tests/                    # pytest
```

`runs/` 是某次执行产物，不要当题目档案改。

---

## 配置要点

| 变量 | 含义 |
|------|------|
| `OPENAI_API_BASE` / `OPENAI_API_KEY` | OpenAI 兼容端点 |
| `MATH_AGENT_*_MODEL` | 默认 / coder / 强模型 / 视觉；一律 `openai/<name>` |
| `MATH_AGENT_ALLOW_CODER_LLM=1` | 无 T-19 / inject 时允许 S9 调 LLM 写码（默认不要开） |
| `MATH_AGENT_RAG_ENABLED` | 保持 `0` |

`MATH_AGENT_CODER_DETERMINISTIC`、`MATH_AGENT_WRITER_DETERMINISTIC`、`MATH_AGENT_OFFLINE_REVIEW` 只用于离线回归，不是做题配置。

---

## 文档

| 你想… | 读 |
|--------|----|
| 30 秒上手（人） | [docs/current/](docs/current/README.md) |
| 现在是什么状态 | [00-体系现状与原则](docs/00-体系现状与原则.md) |
| 新题怎么做 | [brief-playbook](docs/brief-playbook.md) → [操作面契约](docs/实现计划-8-20/8-27-操作面契约.md) |
| 端到端一张图 | [内外全流程总纲](docs/内外全流程总纲.md) |
| 要不要改代码 | [agent 协作协议](docs/agent协作协议.md) |
| 抽任务 / 查决策 | [8-27 完整图景](docs/8-27-完整图景/README.md) · [07 决策表](docs/实现计划-8-20/07-待决策与超范围.md) |
| 文档治理 / 审计 | [文档治理约定](docs/文档治理约定.md) · `python scripts/audit_docs.py` |

完整索引：[docs/README.md](docs/README.md)。`docs/archive/` 不是现行事实来源。

---

## 开发与验证

```bash
uv run --extra dev pytest -q
npm test
python scripts/audit_docs.py
```

大改造后的验证集与运行记录在 [docs/验证/](docs/验证/README.md)。论文运行是否合格看 `completion.json`、证据角色和闸门报告，不把「生成了文件」当成功。

历史全量基线：2026-08-20 为 810 passed / 4 skipped；2026-08-27 实测 949 passed / 4 skipped。D-022 之后用例续增，**以当前 `pytest -q` 为准**。

---

## FAQ

<details>
<summary><strong>还能当上游那样一键出 PDF 吗？</strong></summary>

可以跑 S9，但不作为本 fork 的承诺。无参考实现时必须 `--allow-coder-llm`；门禁不过即停；PDF 仍可能 `degraded`。竞赛主路径是 S0–S8 产出可溯源的 `paper.md`。
</details>

<details>
<summary><strong>支持哪些赛事？</strong></summary>

题面与 brief 按题准备即可（MCM/ICM、国赛、五一杯、MathorCup 等都跑过）。`--template gmcm` 仍可切 `gmcmthesis`。体系不内置某届专用求解器。
</details>

<details>
<summary><strong>崩溃了怎么续？</strong></summary>

S9：`status` / `watch` 看 `failure.json`，再 `recover` 或 `restart --from coder`。人审点用 `resume --approve` / `--no-approve`。操作面（S0–S8）没有「回退到 Sx」命令，改产物后从对应阶段重跑。
</details>

<details>
<summary><strong>本仓和上游如何同步？</strong></summary>

`origin` 指向上游 `123-qw-as/Beacon`，`fork` 指向 `Avalianfeng/Beacon`。操作面、闸门、brief 硬信号是 fork 侧主线；合并上游时不要把「supervise 作默认路径」或物流特化带回来。
</details>

---

## License

上游 README 声明 MIT。本仓根目录暂无 `LICENSE` 文件；再分发前需补齐并保留上游版权说明。

---

<p align="center">
  <sub>Fork of Beacon · 方向先定，证据后随。</sub>
</p>
