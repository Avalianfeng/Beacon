# Beacon 控制面愿景（短稿）

> 状态：愿景 / 不进入本轮实现（2026-08-04）
> 观察面实施方案见 [`PLAN-console-progress-management.md`](PLAN-console-progress-management.md)。

## 一句话

默认仍无人值守跑完；人需要时，在**安全点**用少量命令介入——而不是运行中任意改图。

## 目标体验

1. **开跑后永远能看** → 由观察面交付（`watch` / `progress.jsonl`）。
2. **少数断点能问人** → 先把现有 `human_review` 做成清晰等待；再按需增加极少数可选断点（例如论文分过低时询问），不在每个 critic 打断。
3. **空闲 / 暂停时能重做指定章节或阶段** → 如 `rewrite --section conclusion`、定点 `rerun` 某阶段；必须声明下游失效范围，遵守证据角色与 finalizer 门禁。
4. **预设简要流程，不运行中改拓扑** → `full` / `fast` / `write-only` 等 profile，映射到已有开关与跳过策略；不做通用 DAG 编辑器。

## 架构约束（必须遵守）

- 同一 `out` 仍只有一个写者；人的指令进磁盘请求（例如 `control.jsonl`），由 supervisor 在**节点边界**消费。
- 禁止在任意中间 checkpoint 上随意 `update_state` / 跳转（易错路由 `next_node`）。
- 交互不得绕过 runner 质量门禁、证据隔离与 finalizer 原子收口。
- 无操作员时行为与今天一致（`--no-interrupt` / 自动监管照旧）。

## 建议落地顺序（未来）

| 步 | 内容 | 依赖 |
| --- | --- | --- |
| C0 | 观察面提示「下一步命令」（只读） | 观察面阶段 1 |
| C1 | 交互式人审：暂停可见 + `approve` / `reject` 体验打通 | C0 |
| C2 | 暂停/空闲时章节或阶段重做（带爆炸半径） | C1 + writer/阶段边界设计 |
| C3 | 启动前 profile（简要流程预设） | 与 C1 可并行调研 |
| C4 | 暂停时补充/替换附件并失效下游（可选） | C2 |

## 非目标

- 运行中随时改任意 state 字段或拖拽重排节点。
- 用控制面替代 Web UI 的完整工作台（控制面先服务 CLI；协议可复用）。
- 用交互通道代替 `repair_final_run.py` 或绕过正式收口。

## 与观察面的关系

```text
progress.jsonl     → 机器可读「发生了什么」（观察）
control.jsonl      → 机器可读「请在安全点做什么」（控制，未来）
supervisor + lock  → 唯一执行者
watch / 未来 attach → 人的眼睛（与可选的手）
```

两份契约都落在 `out/`，CLI、Web、Agent 宿主可共用；本轮只建观察侧。
