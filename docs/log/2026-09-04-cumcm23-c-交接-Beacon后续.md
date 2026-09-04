<!-- doc: type=handoff status=active updated=2026-09-04 -->
# 交接 · cumcm23-c 研究会话 → Beacon 后续（验证机制）

> **给谁**：继续操作 Beacon 的会话（可在原研究会话或新开）。  
> **主会话本轮**：只盘点 + 试探 S4/S5 入口；**不代跑完** S5–S8。  
> **人闸**：按主人指示视为**已通过**（去高瓜 28 + brief 抽查）。

---

## 1. 一句话状态

研究已收束；`brief.json` 已 check OK；**S4 预检已通过**（blockers=[]）。  
**S5 证据链未通**：已 `reference add` 薄入口，但 `reference run` 因题根路径解析失败而挂住——下一会话先修入口再跑 verify/recertify。

---

## 2. 磁盘真相（勿靠聊天记忆）

题根：`E:\git_clone\Beacon\problems\cumcm23-c\`

| 路径 | 含义 |
|---|---|
| `_研究日志.md` / `解题说明.md` / `经验与坑.md` / `exploration.md` / `brief草稿.md` | 研究外显 |
| `brief.json` | schema v2；`brief check` OK；39 条 |
| `研究/data/` `研究/scripts/` `研究/figures/` | 实算资产 |
| `研究/beacon_ref/_entry.py` | S5 适配源（已 add 进 `source/reference/`） |
| `source/reference/_entry.py` | 当前登记副本（与上同源；**路径有 bug**） |
| `runs/cumcm23-c-preflight/preflight.json` | S4：`ok=true`，`blockers=[]` |
| `认知地图集/` | 地图 / Diff / 清点（含领域知识，不在题根） |

关键数（与 CSV/JSON 对齐）：

- 回测 MAE：BLEND≈12.96 ＜ WD90≈17.77 ＜ YOY≈28.15  
- Q2 周：补货≈2363 kg，收益代理≈3503  
- Q3 主方案：**去高瓜 28**，收益代理≈795  

拍板工作假设仍是 `1=A…8=A+B`；计算微调 = Q3 上架前剔负毛利高瓜 → 28（日志有据）。

---

## 3. 定稿站位

| 站 | 状态 |
|---|---|
| 10-s5 研究 | ☑ |
| 11-s3 brief | ☑ 机器侧；人闸按指示通过 |
| **12-s4 预检** | ☑ 已跑 `--dry-run` |
| **13-s5 证据** | ☐ **下一站（卡在 reference run）** |
| 14–16 论文/评审/验收 | ☐ 人定是否开；探索性可停 |
| 17 S9 | 默认不跑 |

定稿入口：`全流程分析/全流程定稿/`  
盘点记录：`docs/log/2026-09-04-cumcm23-c-研究收束盘点.md`  
验证勾选：`docs/验证/运行记录-2026-09-04.md`（B/C 已 PASS；S4 本交接补记）

---

## 4. 下一会话建议命令（按序）

工作目录：`E:\git_clone\Beacon`

### 4.1 先修 S5 入口路径（必须）

`reference run` 时 `__file__` 常不在 globals（exec），入口掉进 `cwd=runs/...`，读不到 `研究/data`。

修 `problems/cumcm23-c/研究/beacon_ref/_entry.py`（再 `--force` add），例如优先：

1. `Path(os.environ["MATH_AGENT_DATA_DIR"]).parent / "研究" / "data"`（若 data_dir=source）  
2. 或显式：`Path(r"E:\git_clone\Beacon\problems\cumcm23-c") / "研究" / "data"`  
3. 本地冒烟：`python` 跑通打印 `RESULT:` 后再 add

然后：

```text
uv run math-agent reference add --problem problems/cumcm23-c/problem.json --solver problems/cumcm23-c/研究/beacon_ref --entry _entry.py --force

uv run math-agent reference run --problem problems/cumcm23-c/problem.json --out runs/cumcm23-c-reference

uv run math-agent reference verify --problem problems/cumcm23-c/problem.json --evidence runs/cumcm23-c-reference/evidence.json

uv run math-agent reference recertify --problem problems/cumcm23-c/problem.json --evidence runs/cumcm23-c-reference/evidence.json --actor "<会话标识>" --notes "人闸已过；读研究/data；Q3=去高瓜28" --verdict pass
```

期望产物：

- `runs/cumcm23-c-reference/evidence.json`  
- `problems/cumcm23-c/evidence-package.json`  
- `problems/cumcm23-c/independent-review.json`  

`problem stage cumcm23-c --json` 应出现 S5 完成、next→S6（或缺 paper 相关）。

### 4.2 可选：机制回归（不挡本题）

`docs/验证/验证集-2026-08-29-D022-D023.md` 相关 pytest——有空再跑。

### 4.3 S6+（人定）

```text
reference tables / paper / expand
review-check --brief problems/cumcm23-c/brief.json --paper ... --evidence ...
accept（须人批准）
```

本题探索性真跑允许停在 S5。勿默认全图 `run`（无 `--dry-run`）= S9。

---

## 5. 已知缺口（告知即可）

| 项 | 说明 |
|---|---|
| `d007_missing: 领域知识.md` | 正文在 `认知地图集/清点/领域知识.md`，题根无同名文件；stage 会报缺，可拷贝或改检测（非 S5 硬挡） |
| brief.problem_id WARN | dry-run 曾警告 id 与题目标题串比对；check 仍 OK，可忽略或以后对齐 |
| 缺可选 ML 库 WARN | sklearn 等；本题入口不依赖 |
| 扩33 旧对照 | 研究已否证（需求未守恒）；勿再当更优证据 |

---

## 6. 禁止

- 联网搜本题题解 / 优秀论文当依据  
- 手改 `研究/data` 绑定数字装进论文  
- 主会话本轮未授权：不代写 paper、不代 accept、不跑 S9 全图  

---

## 7. 可粘贴开工白（给下一会话）

```text
你接手 cumcm23-c 的 Beacon 后续。人闸已通过。读：
docs/log/2026-09-04-cumcm23-c-交接-Beacon后续.md
problems/cumcm23-c/_研究日志.md
problems/cumcm23-c/brief.json

当前：S4 已过（runs/cumcm23-c-preflight）。S5 卡在 reference run 路径。
请修 研究/beacon_ref/_entry.py 的题根解析 → add --force → run → verify → recertify。
不要默认开论文链；S6+ 先问人。工作区 E:\git_clone\Beacon。
```

---

## 8. 本交接已执行（2026-09-04 续会话）

S5 链已通。详见 `docs/log/2026-09-04-cumcm23-c-S5证据链.md`。下一问人：是否开 S6 `reference paper`。
