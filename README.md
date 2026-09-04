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
  <a href="#正式用法"><strong>用法</strong></a> ·
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

正式用法只在 [全流程定稿 00](全流程分析/全流程定稿/00-正式闭环.md)（本 README 是摘要，冲突时信定稿）：

1. **图外**找方向、算明白、压成 `brief.json`。本地自己跑完只是准备，**不是结束**。
2. **启动图**：登记代码是改代码插座（不是交差；coder LLM 默认关）；critic / 门禁停机后交回人改，再登记再跑。
3. 论文从 **writer 链**出完整初稿；人少量改后 `accept`。

交付以 `paper.md` 为主；PDF 只做编译预览。

---

## 相对上游改了什么

上游（[123-qw-as/Beacon](https://github.com/123-qw-as/Beacon)）把 **Web UI + 完整 LangGraph 流水线**写成主产品。本 fork 保留这条图，但把它降为工具层，并拆掉题域特化。

| 维度 | 上游 | 本 fork |
|------|------|---------|
| 主路径 | 一键跑图 | 本地算明白 → brief + 登记 → 启动图；写作在 writer |
| 方向从哪来 | 图内 Analyst 拆题 | 图外探索 / Diff / 研究，再压成 `brief.json` |
| 求解代码 | coder 默认 LLM 生成 | 本地写；`reference` / `inject` 登记；LLM 须 `--allow-coder-llm` |
| 失败策略 | critic 循环再试 | 门禁停机 → **交回手改** → 再登记再跑 |
| 终稿 | 强调 PDF | `.md` 为主；PDF 仅预览 |
| RAG / 题域求解器 | 可选 / 曾含物流特化 | 不启用 / 已拆除 |

不要用旧操作面编号 S0–S9 当「两套主路径」；那些只是命令标签。决策入口：[00-体系现状](docs/00-体系现状与原则.md)。

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

```bash
uv run math-agent --help
uv run math-agent problem stage mcm51-c --json
```

只跑 Web 时再 `npm install` 与 `npm start`。CLI 不依赖前端。

---

## 正式用法

完整时间顺序与角色切换：**只读** [全流程定稿 00](全流程分析/全流程定稿/00-正式闭环.md)。下面是五幕摘要。

| 幕 | 做什么 | 定稿 |
|----|--------|------|
| 一 · 方向 | 导入 → EDA → 外/本地独立探索 → Diff → 人拍板 | [01–09](全流程分析/全流程定稿/README.md) |
| 二 · 算明白 | 研究者编码、实验、出数（**≠ 交卷**） | [10](全流程分析/全流程定稿/10-s5-求解推进.md) |
| 三 · 手柄 | `brief.json` 定稿，驾驭图 | [11](全流程分析/全流程定稿/11-s3-brief定稿.md) |
| 四 · 启动图 | 预检 → 登记插座 → **writer 出论文** | [12–14](全流程分析/全流程定稿/14-s6-论文装配.md) |
| 五 · 收口 | critic→手改循环；人评 → `accept` | [15–16](全流程分析/全流程定稿/15-s7-评审.md) |

### 启动图（产品化入口）

登记不是交差：是给本机代码插上 Beacon 的改代码插座。无冻结代码时 coder 立即停，除非 `--allow-coder-llm`（默认不要开）。

```bash
# 证据已齐、从写作段冷启动（常用）
uv run math-agent run \
  --problem problems/<题>/problem.json \
  --brief problems/<题>/brief.json \
  --from writer \
  --evidence runs/<题>-reference/evidence.json \
  --out runs/<题>-writer-graph

# critic / 门禁停机后：改代码或 brief，再登记，再从 writer 重跑
uv run math-agent restart --out runs/<题>-writer-graph --from writer --reason "…"

# 交棒材料（停机时也会自动写出）
uv run math-agent critic-handoff --out runs/<id>

uv run math-agent watch --out runs/<run>
```

骨架、`reference expand`、会话手写 prose **不是**正式写作终态。Web UI 只驱动图，不会替你做探索 / Diff / brief。

### 题目录（做题时认这个）

```text
problems/<题>/
  problem.md|json   data_profile.md     ← CLI
  exploration.md                        ← 研究收束后人读，不是对撞地图
  _派发/{本地,diff,研究}.md
  eda/   source/                        ← xlsx/pdf 本机保留、不入库
  source/reference/ | source/inject/    ← 登记代码（插座）
  认知地图集/外部|本地|diff|清点
  _研究日志.md  解题说明.md  经验与坑.md
  brief.json
```

`runs/` 是某次执行产物，不要当题目档案改。

硬禁止（定稿口径）：先 brief 后对撞；搜本题题解当依据；产本地地图时读外部地图；只把关键结论留在对话框。

---

## 项目结构

```
Beacon/
├── 全流程分析/全流程定稿/   # 用法唯一指导（先读 00）
├── problems/<题号>/          # 题目档案（见上）
├── src/math_agent/           # CLI、graph、nodes、闸门
├── scripts/                  # check_paper_numbers / check_l4_gates / …
├── docs/                     # 产品指针；不做第二套流程说明书
├── frontend/                 # 可选 Web 工作台
└── tests/                    # pytest
```

---

## 配置要点

| 变量 | 含义 |
|------|------|
| `OPENAI_API_BASE` / `OPENAI_API_KEY` | OpenAI 兼容端点 |
| `MATH_AGENT_*_MODEL` | 默认 / coder / 强模型 / 视觉；一律 `openai/<name>` |
| `MATH_AGENT_ALLOW_CODER_LLM=1` | 无登记代码时允许 coder 调 LLM（默认不要开） |
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

验证集与运行记录在 [docs/验证/](docs/验证/README.md)。论文运行是否合格看 `completion.json`、证据角色和闸门报告，不把「生成了文件」当成功。以当前 `pytest -q` 为准。

---

## FAQ

<details>
<summary><strong>还能当上游那样一键出 PDF 吗？</strong></summary>

可以跑图，但不作为「一键出赛」承诺。无登记代码时必须 `--allow-coder-llm`。竞赛路径是：本地算明白 → brief + 登记 → writer 出 `paper.md`。
</details>

<details>
<summary><strong>支持哪些赛事？</strong></summary>

题面与 brief 按题准备即可（MCM/ICM、国赛、五一杯、MathorCup 等都跑过）。`--template gmcm` 仍可切 `gmcmthesis`。体系不内置某届专用求解器。
</details>

<details>
<summary><strong>崩溃了怎么续？</strong></summary>

`status` / `watch` 看停机原因与 `critic-handoff`；改代码或 brief 后再登记，用 `restart --from writer`（或 `--from coder`）续跑。人审点用 `resume --approve` / `--no-approve`。
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
  <sub>Fork of Beacon · 方向先定，证据后随 · 本地算完 ≠ 结束。</sub>
</p>
