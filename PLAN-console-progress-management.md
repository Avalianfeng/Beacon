# Beacon 控制台观察面 · 设计方案

> 状态：待确认（2026-08-04 修订；初稿基于 `main@4fc3ab1`）
> 定位：**观察面（Observation）**——开跑后永远能看；不指挥任务、不改 checkpoint。
> 控制面愿景见 [`PLAN-console-control-plane.md`](PLAN-console-control-plane.md)（另页，不进入本轮实现）。

## 一、目标

1. 任务运行期间，控制台实时可见：supervisor 状态、当前节点、恢复次数、日志尾部；阶段 2 起再补节点链与 LLM 统计。
2. 观察端与运行端解耦：观察进程只读磁盘产物，不碰运行进程；支持后台任务、断线重连、多观察者并发。
3. 终态时给出**唯一下一步命令提示**（不执行控制动作）。
4. 保持 CLI、Web UI 与公开状态字段向后兼容（只新增命令与可选参数）。

## 二、产品分层（本方案只做第一层）

| 层 | 职责 | 本方案 |
| --- | --- | --- |
| 观察面 | 永远能看：状态、日志、事件流 | **本文件，优先实施** |
| 控制面 | 少数断点问人；空闲/暂停时重做章节或阶段 | 见控制面愿景，后续 |
| 编排面 | 预设简要流程 profile，不运行中改拓扑 | 见控制面愿景，更后 |

默认生产路径仍是无人值守监管（`start` / `supervise`）。观察面是叠加能力，不是替代。

## 三、简单上手（默认配方）

```text
uv run math-agent start --problem <题面.json> --out runs/my-run --no-interrupt
uv run math-agent watch --out runs/my-run
```

约定：

1. `start` 成功后的提示**必须**包含 `watch` 命令行（保留现有 `status` / 日志路径亦可）。
2. 默认 `--mode auto`：TTY 用面板+日志，非 TTY 纯文本；快捷键是增强，不要求新人学习。
3. 三种用户意图在文档中写清，避免混用：
   - **接着看** → `watch`（只读）
   - **接着跑** → 已有 supervisor 则等待；否则 `supervise-recover` / `recover`
   - **推倒重来** → 换 `--out`，或显式 `--force`（默认劝换目录）

## 四、现状事实（已核实）

| 事实 | 位置 | 影响 |
| --- | --- | --- |
| 节点进出已有日志 `[pipeline] node: <name>` | `graph.py` `_wrap()` | 阶段 1 可从日志看到当前节点进出 |
| `run`/`resume`/`recover` 阻塞式 `g.invoke()`，无中间 UI | `cli.py` | 前台运行不可见；正式用法是 `start`/`supervise` |
| `supervise` worker 继承 stdout；后台进 `supervisor.log` | `supervisor.py` | watch 跟日志即可覆盖后台模式 |
| `supervisor.json` 约 5 秒心跳 | `supervisor.py` | 状态面板主数据源 |
| `inspect_checkpoint()` → next_node / final_status | `supervisor.py` | 当前节点判断现成 |
| `status` 已做 supervisor 与 verified completion 的 stale 调和 | `cli.py` | watch **必须复用**同一套 reconcile |
| `trace.json` 运行中非实时 | `tracing.py` | 不拿它做实时；阶段 2 用 `progress.jsonl` |
| `rich>=13.7` 已在依赖 | `pyproject.toml` | 零新依赖 |

## 五、设计原则

1. **观察端只读**：不向运行进程发信号；`q` / `Ctrl+C` 只退出观察进程。
2. **向后兼容**：不改 `run` / `resume` / `recover` / `supervise` / `status` 语义。
3. **事件流与日志分离**：日志给人看；`progress.jsonl` 给机器与面板（阶段 2）。
4. **非 TTY 降级**：管道 / CI 无 ANSI。
5. **终态可行动**：面板在 paused / blocked / completed / degraded / rejected 时展示下一步 CLI，但仍不代为执行。
6. **事件写入 best-effort**：写 `progress.jsonl` 失败不得拖垮 pipeline；不写完整 prompt / 附件内容。

## 六、阶段 1：`math-agent watch`（零侵入）

### 命令签名

```text
math-agent watch [--out runs/latest] [--thread default] [--mode auto|log|panel] [--tail 200] [--refresh 1.0]
```

### 阶段 1 面板承诺（不画超）

阶段 1 **不承诺**完整「已完成节点链」和实时 LLM 统计（无可靠数据源；日志解析在 recover 重跑时会重复）。

```text
┌ Beacon run  runs/my-run  (thread=default) ─────────────┐
│ status: running   worker_pid: 4123   attempt: 1        │
│ recoveries: 2/20   same_node_failures: 0               │
│ next_node: writer_section   checkpoint: yes            │
│ heartbeat: …   (reconciled；stale 时显示 effective)      │
├────────────────────────────────────────────────────────┤
│ [pipeline] node: writer_section                        │
│ [supervisor] starting worker: recover (attempt 3)      │
│ …（supervisor.log 尾部）                                 │
└────────────────────────────────────────────────────────┘
  下一步: （running 时可空；paused/blocked/… 时给唯一下一条命令）
  q / Ctrl+C 退出跟随（不杀任务）
```

### 终态与意外时的提示（只读提示）

| 状态 | 面板行为 | 提示方向（示例） |
| --- | --- | --- |
| running | 持续刷新 | — |
| paused（`human_review`） | 高亮暂停 | `supervise-resume --approve` / `--no-approve` |
| blocked | 展示 failure 摘要 | 先修配置；再 `supervise-recover` 或按 `failure.json` 处理 |
| completed / degraded / rejected | 冻结面板或摘要后退出 | 指向 `completion.json` / `report` |
| stale | 以 verified completion 为准 | 与 `status` 一致 |
| BUSY / 锁占用 | 标明另一进程在写 | 继续只读跟随，不暗示 `--force` |
| 心跳过期 / 死 PID | 走 `reconcile_supervisor_state` | 显示「监督进程可能已退出」+ recover 提示 |
| 等待任务创建 | 文件未齐 | 「等待任务创建…」（支持先 watch 后 start） |

可选：`--follow-exit` 在终态自动结束 watch（默认可保持跟随，由 `q` 退出）。

### 交互键（MVP 可极简）

| 键 | 行为 | MVP |
| --- | --- | --- |
| `q` / `Ctrl+C` | 退出跟随，绝不杀任务 | 必须 |
| `f` | 面板+日志 / 纯日志 / 纯面板 | 阶段 1.5 |
| `p` | 暂停/恢复日志滚动 | 阶段 1.5 |
| `d` | 展开最近事件详情 | 阶段 1.5 |

### 实现要点

- 新模块 `src/math_agent/watch.py`；复用 `inspect_checkpoint` / `reconcile_supervisor_state`。
- 主线程 `rich.Live` + 后台线程按 offset 增量读 `supervisor.log`。
- 日志被截断或轮转时：若文件变小或 inode/尺寸异常则重定位，避免空白或错乱。
- 非 TTY → `tail -f` 风格纯文本。
- Windows：优先保证轮询渲染与退出安全；键盘增强可后置。

## 七、阶段 2：`progress.jsonl` + 日志增强

### 文件格式（`out/progress.jsonl`，append-only）

```jsonl
{"ts": 1722754800.123, "type": "run_boundary", "attempt": 1, "epoch": 1}
{"ts": 1722754800.200, "type": "node_start", "node": "writer_section", "attempt": 1}
{"ts": 1722754800.456, "type": "llm_call", "model": "openai/gpt-4o", "prompt_tokens": 8421, "completion_tokens": 512, "latency_ms": 3421}
{"ts": 1722754900.789, "type": "node_end", "node": "writer_section", "duration_ms": 20234}
{"ts": 1722754900.900, "type": "stage", "stage": "final"}
{"ts": 1722754920.100, "type": "error", "node": "writer_section", "kind": "timeout"}
```

要求：

- 带 `attempt` / `epoch`（或等价 run 边界事件），避免 recover / `--force` 后节点链污染。
- `--force` 新跑：截断或轮转 `progress.jsonl`，与 checkpoint 清理同生命周期。
- `error.kind` 尽量对齐现有 `FailureRecord`（如 `interrupted` / `incomplete` / timeout 等）。
- 只记 model / tokens / latency / failover；**不写**完整 prompt、响应正文、附件内容。

### 写入点

| 位置 | 事件 | 改动 |
| --- | --- | --- |
| `graph.py` `_wrap()` | `node_start` / `node_end` | 极小；顺带节点结束耗时日志 |
| `llm.py` `complete()` 成功/failover | `llm_call` / 日志行 | best-effort |
| CLI / supervisor 异常分支 | `error` | 极小 |
| 新 run / force / worker 启动 | `run_boundary` | 与清理逻辑对齐 |

### 日志增强

- `[pipeline] node: writer_section (stage=final)` + 结束耗时行。
- `[llm] failover modelA→modelB`——恢复过程可见。

### watch 升级

面板改为消费 `progress.jsonl`：当前节点、按 epoch 过滤的节点链、LLM 统计、最近事件。`supervisor.log` 退居「原始日志」视图。

## 八、阶段 3（可选，低优先级）

- **不做**默认的 `run --live` 主路径（与短会话宿主 + 长流程监管冲突）。
- 若单终端有强需求：优先考虑 `supervise` 状态摘要行，或文档强调「另开终端 `watch`」。
- `invoke → stream` 改造默认不做，需单列评估与测试。

## 九、测试与验证

1. **单测**（`tests/test_watch.py`）：日志增量与截断重定位、面板状态组装（含 reconcile/stale）、事件写入与坏行跳过、非 TTY 降级、`--force` 后事件边界。
2. **兼容性**：现有测试全绿；既有命令语义不变。
3. **手工**：`start` + `watch` → 节点推进可见 → `q` 后 worker 仍存活；模拟 running→recover→paused→终态，提示命令正确。
4. **文档**：`docs/` 中文说明 + README CLI 表补 `watch`；指向控制面愿景但不承诺实现日期。

## 十、风险清单

| 风险 | 应对 |
| --- | --- |
| rich Live 在 Windows 旧终端异常 | 非 TTY 降级；稳定组件；键盘后置 |
| `watch` 误杀任务 | 只读；信号处理只清理本进程渲染 |
| 事件与 checkpoint 并发 | append + 读端跳坏行；写入失败不抛进主流程 |
| 阶段 1 数据不足却画完整节点链 | 阶段 1 收缩承诺；链与 LLM 统计放阶段 2 |
| 与控制面混淆 | 文档与 UI 文案明确「只看不控」；控制命令另页 |

## 十一、实施顺序

**阶段 1 → 阶段 2**，各自可验证、可单独 PR。阶段 3 默认搁置。控制面不在本方案范围。
