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
  <a href="#agent-怎么用-beacon"><strong>用法</strong></a> ·
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

Beacon 帮建模竞赛走完「从题面到可溯源论文」。本 fork **不承诺无人值守出好论文**。

正式用法（详情只在 [全流程定稿 00](全流程分析/全流程定稿/00-正式闭环.md)）：

1. 本地 agent 探索、写代码、算数、起草 brief。**自己跑完不是结束。**
2. 启动 LangGraph：brief 驾驭方向；登记代码是改代码插座（coder LLM 默认关）；critic 照用。
3. 图跑通后由 **writer 链**出完整初稿；人少量改后 `accept`。

交付以 `paper.md` 为主；PDF 只做编译预览。

---

## 相对上游改了什么

上游（[123-qw-as/Beacon](https://github.com/123-qw-as/Beacon)）把 **Web UI + 完整 LangGraph 流水线**写成主产品：粘贴题面 → 自动分析 / 建模 / 写码 / 作图 / 写论文 / 出 PDF。本 fork 保留这条图，但把它降为工具层，并拆掉题域特化。

| 维度 | 上游 | 本 fork |
|------|------|---------|
| 主路径 | 一键跑 14 阶段图 | 本地算明白 → 启动图（brief + 登记代码）；不是「S8 出骨架即结束」 |
| 方向从哪来 | 图内 Analyst 拆题 | 图外探索/对撞/研究，再压成 `brief.json` 驾驭图 |
| 求解代码 | coder 默认 LLM 生成 | 本地写；`reference` / `inject` 登记；LLM 须 `--allow-coder-llm` |
| 失败策略 | critic 循环再试 | 门禁停机 → **交回 agent 手改** → 再登记再跑 |
| 质量兜底 | 节点评分 + HITL | 机械闸门 + critic |
| 题域 | 曾含物流专用求解器 | 已拆除；只留通用闸门 + 题级 brief |
| RAG | 可选向量检索 | 不启用 |
| 终稿 | 强调 PDF | `.md` 为主；PDF 仅预览 |
| 论文谁产 | 流水线 writer | **仍是 writer 链**；工作面只做 Word / 少量改 |

命令：`problem` / `brief` / `reference` / `review-check` / `accept`，以及 `pause` / `restart`。

决策入口：[00-体系现状](docs/00-体系现状与原则.md)。旧 D-xx 长文在 `docs/archive/adr-历史/`。

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

应看到做题相关命令。已有范本：

```bash
uv run math-agent problem stage mcm51-c --json
```

只跑 Web 时再 `npm install` 与 `npm start`。CLI 不依赖前端。

---

## Agent 怎么用 Beacon

完整时间顺序与角色切换：**只读** [全流程定稿 00](全流程分析/全流程定稿/00-正式闭环.md)。

命令仍可用（`problem` / `brief` / `reference` / `review-check` / `accept`），但不要按「S6=出骨架、S9=可选所以图不用」来理解。登记之后要启动图；论文从 writer 出。

LangGraph 还在。无冻结代码时 coder 立即停，除非 `--allow-coder-llm`（默认不要开）。

```bash
uv run math-agent watch --out runs/<run>
uv run math-agent restart --out runs/<run> --from coder
```

`--from writer` 尚未产品化（定稿 14）。Web UI 驱动的是图，不会替你做探索/brief。

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
├── docs/                     # 产品指针；用法在 全流程分析/
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
| **用法（唯一）** | [全流程定稿 00](全流程分析/全流程定稿/00-正式闭环.md) |
| 各段怎么做 | [全流程定稿](全流程分析/全流程定稿/README.md) |
| 现在卡在哪 | [docs/current/](docs/current/README.md) |
| 改不改机制 | [agent 协作协议](docs/agent协作协议.md) |
| 产品定位 | [00-体系现状](docs/00-体系现状与原则.md) |
| 旧文 | [docs/archive](docs/archive/README.md) · [全流程分析/archive](全流程分析/archive/README.md) |

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

可以跑图，但不作为「一键出赛」承诺。无参考实现时必须 `--allow-coder-llm`。竞赛路径是：本地算明白 → 启动图 → writer 出 `paper.md`。
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
