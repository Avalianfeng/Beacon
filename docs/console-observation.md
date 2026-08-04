# 控制台观察面

> 现行说明。设计背景见仓库根目录 [`PLAN-console-progress-management.md`](../PLAN-console-progress-management.md)；
> 控制面愿景见 [`PLAN-console-control-plane.md`](../PLAN-console-control-plane.md)（尚未实现）。

## 默认用法

```powershell
# 网页或 CLI 启动任务后，可直接：
uv run math-agent watch

# 仍可显式指定目录
uv run math-agent watch --out runs/ui-latest
```

`watch` / `status` 省略 `--out` 时自动解析顺序：进行中的任务 → `runs/.beacon-active.json` 指针 → 最近一次含 `supervisor.json` 的目录。  
面板顶部会显示解析后的绝对路径（及 `active-running` / `pointer` / `recent` 来源）。

Web UI 刷新后通过 `GET /api/active-run` 用同一套规则接回任务（内存里的 run id 会丢，但磁盘上的 pipeline 不会），原有轮询与 SSE 刷新机制保持不变。

`watch` **只读**跟随 `supervisor.json`、`supervisor.log`、checkpoint 与 `progress.jsonl`。
`q` / `Ctrl+C` 只退出观察进程，不会终止后台任务。

## 三种意图

| 意图 | 做法 |
| --- | --- |
| 接着看 | `math-agent watch --out <run>` |
| 接着跑 | 监督仍在则等待；否则 `supervise-recover` / `recover` |
| 推倒重来 | 换 `--out`，或显式 `--force`（默认建议换目录） |

## 终态提示

面板在 `paused` / `blocked` / `completed` / `degraded` / `rejected` / `stale` 时给出**下一步 CLI 文案**，但不代为执行。  
可选 `--follow-exit`：在 completed/degraded/rejected/blocked 时自动结束观察。

## 事件文件

`out/progress.jsonl` 为 append-only 事件流（节点进出、LLM 统计、run_boundary、error）。
`--force` 会截断并写入新的边界事件。写入失败不影响主流程；不记录完整 prompt 或附件内容。
