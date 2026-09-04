<!-- doc: type=contract status=active updated=2026-09-05 -->
# Agent 与 Beacon 协作协议

> **用法正文**：[全流程定稿 00](../全流程分析/全流程定稿/00-正式闭环.md)。本文只留边界，避免和 00 各写一套。  
> 要不要改 Beacon 机制：先看 00 里缺的是不是「本地该做的事」。

---

## 闭环（摘要）

本地探索 / 编码 / 算数 / 起草 brief → **自己跑完 ≠ 结束** → 启动 Beacon（brief 驾驭 + 代码登记）→ 图跑执行 / critic / writer → 失败则交回手改 → 跑通出论文。

代码登记 = 改代码插座（替代 coder LLM），不是交差。  
brief = 暂定方向手柄。  
critic 照用。

---

## 职责

| 方 | 职责 |
|---|---|
| **agent** | 探索、写/改代码、算数、维护 brief；读 critic 手改；判断 brief 不够还是体系方向更好 |
| **Beacon** | LangGraph 执行/评审/写作；机械闸；checkpoint |
| **人** | 拍板、评论文、accept；工作面 Word/少量改 |

---

## 接口（命令）

| 接口 | 角色 |
|---|---|
| `brief.json` + `brief check` | 方向手柄 |
| `reference add` / `--force` / `source/inject/` | 改代码插座 |
| `reference run` | 跑冻结脚本 → `evidence.json` |
| `run --from writer --evidence …` | 冷启动写作段（接桥） |
| `restart --from coder\|writer` | 门禁停机后重跑编码/写作 |
| `critic-handoff` / `critic-handoff.json` | 停机交棒包（手改依据） |
| writer 链 | 产论文 |
| `review-check` / `accept` | 机械闸与验收 |

`reference expand`、会话手写 prose：应急，非正式终态。

---

## 改机制三问

1. 机械/确定性 → 放 Beacon  
2. 红线相关 → Beacon 校验  
3. agent 脚本 + 现有接口能覆盖 → 只写约定，不建新机制
