<!-- doc: type=guide status=active updated=2026-09-05 -->
# 11 · brief 定稿（方向手柄）

> **第三幕。** 总图：[00](00-正式闭环.md) ⑦ → 上一站 [10-研究会话](10-研究会话.md) → 下一站 [12-预检](12-预检.md)。  
> 理解面：[讲解 §3.1](../讲解-一篇读懂Beacon闭环.md)（方向手柄；为什么还要 plan）。

## 这一段在防什么

研究认识还在人读文档里时，机器无法驾驭。brief 把"已经算过、站得住的方向"压成机器可读的**方向手柄**：各问走法、红线、数据口径、写作要点。它是**暂定的、拿来驾驭 Beacon 的**——不是研究任务单（研究开始时不该有它），也不是圣经（图跑起来方向被证伪就改它，或承认体系侧更好并记账）。

与 plan 的分工在这里钉死：**brief 管"写什么、禁什么"；plan 管"模型长什么样"**（下一站 14 才 build，因为 plan 要给图内 critic 审，和登记一起做）。本站**还没有** plan.json。

## 输入 / 怎么做

输入：`exploration.md`（人读收束）+ `brief草稿.md` + 研究日志。

1. 从人读收束倒推机器字段：`per_question_direction` / `data_notes` / `red_lines` / `formula_notes` / `figure_plan` / `background_knowledge` / `required_discussions`——只压缩**已经用数据验证过**的方向。
2. `math-agent brief check` 过（schema v2）。
3. 红线与分级假设**人认**（红线是图内硬闸的依据，认错会误杀或漏杀）。

人闸：只压缩已验证方向；红线人认。

## 边界

- brief 不驱动对撞/研究（顺序反了 = 先写死再研究，硬禁止）。
- 证伪时二选一（研究者判断）：补 brief 再跑 / 承认体系侧方向更好并记账。
- 改 brief 后若已 `run --plan` 过 → **新开 run**，不能 restart（输入戳）。

## 站终态树

```text
problems/<题>/brief.json    ← 本站产物：方向手柄（schema v2；人认红线）
```

| 资产 | 谁写 | 谁读 | 何时 |
|---|---|---|---|
| `brief.json` | 研究者直写/主会话收口、人认红线 | 图内各节点（注入）、14 plan build | 本站产出；图跑后可改（改=新 run） |

## 自查

- [ ] `brief check` OK；红线/分级假设人认过
- [ ] 只含已数据验证的方向（没有"希望如此"）
- [ ] plan.json 还不存在——它属于下一站 14（和登记一起做）

## 本题状态

cumcm23-c：`brief.json` 已 check OK（schema v2）——细节看题根。
