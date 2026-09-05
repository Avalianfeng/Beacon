<!-- doc: type=guide status=active updated=2026-09-05 -->
# 14 · plan 与登记（把研究结论变成机器可审、可复算的形态）

> **第四幕 · 过境。** 总图：[00](00-正式闭环.md) ⑨ → 上一站 [13-交接文档](13-交接文档.md) → 下一站 [15-启动图](15-启动图.md)。  
> 理解面：[讲解 §3.1–§3.5](../讲解-一篇读懂Beacon闭环.md)（文牒 / 注入 / 插座 / 血缘）。  
> 写法契约：`prompts/登记/契约-代码插座.md` + 两个骨架模板。

## 这一段在防什么

研究结论是"私有的认知"，图是"公有的机器"。过境要防三类失败：

1. **机器审不了**：critic 要审的形态（蓝图/模型卡）研究没给 → `plan.json`（14-A）。
2. **代码接不上**：研究代码的目标是"研究者算明白"，图内代码的契约是"实现模型卡并输出约定行"，两者不同构 → `_entry.py` + inject（14-B），研究代码只是参考。
3. **数字不可复核**：机器无法证明"你算过"→ 登记 + 血缘 + 冒烟复算（14-C），每次改码必须重登记。

**登记不是交差，是给 agent 插上改代码的插座**：替代的是 coder 节点 LLM，不是替代 Beacon。登记可以、也应该多次发生。

## 怎么做（四步，可反复）

### 14-A · plan 卡（图内蓝图 + final 模型卡）

```text
uv run math-agent plan build --brief problems/<题>/brief.json --out problems/<题>/plan.json
uv run math-agent plan check --plan problems/<题>/plan.json --brief problems/<题>/brief.json
```

- v0 自动带 brief→小问/方程锚；**必须手补**：`decision_variables`、`validation_plan.pass_criteria`（数值合理区间）、`recommended_route`、`data_requirements`、题面约束（`source=given`）；coverage 的 `reason` 写清"这条 brief 怎么落地"，不写骨架编号。
- `plan check` 零 token 挡一半打回，**不能**代替 critic 语义分。
- 敏感数字**不写进 plan 当论文事实**：只钉扫参参数名（如 `成本冲击 (cost_shock)`）。

### 14-B · 两张插座代码（契约与骨架在 prompts/登记/）

- `source/reference/_entry.py`：主求解。输出 Q 行 + `RESULT: baseline=ours`（≥3 指标）+ 独立 `RESULT: baseline=<对照名>` 行（finalizer 计数）；**真实 open 声明附件**；执行 cwd 落 PNG（血缘）。
- `source/inject/sensitivity.py`：扫参。每网格一行 `RESULT: parameter=<名> values=[…] results=[…]`；参数名与 plan 钉死的一致；**按研究网格重算**，不抄研究表数字。

### 14-C · 登记与冒烟

```text
uv run math-agent reference add --problem problems/<题>/problem.json --solver problems/<题>/source/reference --entry _entry.py --force
uv run math-agent reference run      --problem problems/<题>/problem.json --out runs/<题>-reference
uv run math-agent reference verify   --problem problems/<题>/problem.json --evidence runs/<题>-reference/evidence.json
uv run math-agent reference recertify --problem problems/<题>/problem.json --evidence runs/<题>-reference/evidence.json --actor "<谁>" --notes "<人闸见交接 §3>" --verdict pass
```

⚠ **两套 run 不是一回事**：

| 命令 | 在哪跑 | 干什么 |
|---|---|---|
| `reference run` | 图外 CLI | 冒烟复算 + 人闸抽查 + `review-check --strict` 对照锚；**不是**论文数字源 |
| `math-agent run --plan` | 图内 | 论文数字 = 图内 execute stdout（下一站 15） |

改代码后必须 `add --force` 再跑（哈希更新，图才吃新码）；改 plan/brief 后新开 run（14 产物变了不能 restart）。

## 边界

- 禁：把研究代码原样塞进 `_entry` 交差；手抄研究数字进 inject；只读摘要不碰附件（血缘必挂）。
- 人闸：recertify 落账（actor/notes/verdict），与交接文档人闸记录对齐。

## 站终态树

```text
problems/<题>/
  plan.json                       ← 蓝图+模型卡（plan check 过）
  source/reference/_entry.py      ← 冻结主求解（哈希登记在 problem.json + reference.json）
  source/inject/sensitivity.py    ← 敏感性扫参（缺 = 正式路径停机）
  reference.json  evidence-package.json  independent-review.json   ← 登记账本
runs/<题>-reference/evidence.json ← 图外冒烟产物（对账锚）
```

## 自查

- [ ] `plan check` 零缺口；`_entry` 冒烟 `verify` 三查过；recertify 已落账
- [ ] `_entry` open 过附件、inject 参数名与 plan 对齐
- [ ] 所有数字能回指 `研究/data` 或由脚本重算（无手抄）

## 本题状态

cumcm23-c：plan.json（check 零缺口）、`_entry.py`（血缘版）、inject 三网格已就位——见题根；写法实例对照 `problems/cumcm23-c/source/`。
