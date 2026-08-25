# 11-可恢复性增强：随时打断/恢复 + 门禁停机人工放行重试

- 建立日期：2026-08-21
- 定位：执行层批次（可恢复性增强）。源于 mcm51-b 首次真跑实证；**不阻塞当前 mcm51-b 重跑**，独立 agent 可接手执行。
- 状态：待执行

---

## 一、背景与动机（mcm51-b 实证）

- 首次 run：42 次调用 / 356k tokens，在 `model_code_consistency` 无主证据 6 轮后门禁停机；
- 根因是守卫误杀（G8：`total_cost` 通用成本名被物流指标守卫拒绝，已修复），但**修根因后只能全新 run**；
- `recover` 实测空转：门禁停机后 checkpoint `next=()`（B05 语义），图没有可续节点；
- 价值：① 守卫误杀类问题从「烧整轮（~36 万 tokens）」降为「人工判定后重试一次」；② 运行中人工介入（pilot 剧本 G6）从「杀进程」升级为「优雅暂停」。

## 二、P0：随时打断/恢复（pause/resume）

**功能需求：**
1. `pause`：向运行中的 run 写暂停请求；worker 在**当前节点结束后**优雅停止（节点内执行不中断，checkpoint 已落）；
2. 恢复：`recover` / `supervise-resume` 清除暂停标记后正常续跑（复用既有恢复路径）；
3. `watch` 面板加 `p`（暂停）/ `c`（续跑）键绑定（若成本可控）；
4. 暂停标记落 run 目录（如 `.pause_request`），恢复后清除。

**行为契约：**
- 暂停只发生在**节点边界**；暂停态 checkpoint `next` 指向下一节点（可恢复态）——**区别于**门禁停机的 `next=()`；
- 不绕过任何门禁；暂停/恢复对 evidence 链零影响。

**验收：**
- 运行中 pause → 状态为 paused → recover 续跑从下一节点开始，无重复/跳过节点；
- 单测（mock 图、无 LLM）：节点边界停止语义、恢复续跑、标记文件生命周期。

**量级：约 200–250 行 / 3–4 文件 / 0.5–1 天。**

## 三、P1：门禁停机人工放行重试（restart --from <node>）

**功能需求：**
1. `restart --from coder --reason <str>`：**仅当** checkpoint 处于门禁停机态（`next=()` 且 gate 诊断 `approved=False`/`over_limit`）时可用；
2. 前置校验：**输入不变性**——brief/problem 哈希与 run_manifest 一致；变了则拒绝并提示全新 run；
3. 回退执行：从 checkpoint 历史找「进入 coder 前」的快照，重置门禁相关计数器（`code_verify_iteration`、无主证据轮次等），重执行 coder 及其后节点；
4. 标注与血缘：run_manifest 记 `restarted` + reason；下游旧产物（steps/insights/gate_diagnostics/failure）失效标注或清理，防止论文引用过期证据。

**语义边界（最重要）：**
- **不绕过门禁**：重试后仍走一致性评审；`restart` 只是「人工判定守卫/方向无问题后，重执行合法节点」；
- 仅服务**门禁停机**态；崩溃态/进行中/人审暂停均拒绝；
- 重试后若再次停机，不自动无限重试（再次停机 = 回到人工，换方向或改 brief 全新 run）。

**验收：**
- 停机态 restart → coder 重试 → 一致性通过（或再次停机且不自动重试）；
- brief/problem 任一变更 → 拒绝；
- 单测：停机→重试→通过；输入变→拒绝；计数器重置；门禁停机外状态→拒绝。

**量级：约 350–550 行 / 4–6 文件 / 1–2 天。技术不确定点：LangGraph checkpoint 历史回退的正确性（需真实 checkpoint 文件验证）+ 门禁计数器存储位置需先探明。**

## 四、明确不做

- **改 brief 后从任意点重来**：B05 语义保留（修 brief 只能全新 run——上游产物基于旧 brief 生成，复用破坏证据链）；
- 通用 rewind（任意节点重做）：P1 真跑验证后再评估。

## 五、关联文件（已知，供接手 agent 核实；不确定的自行查阅）

- `src/math_agent/cli.py`：supervise/run/recover/resume/watch 命令、门禁 stop 映射、`_prepare_run_output`/manifest；
- `src/math_agent/supervisor.py`：worker 生命周期、心跳、失败自动恢复（`run_process_supervisor`）；
- `src/math_agent/checkpointing.py` + `graph.py`：sqlite checkpoint、条件边 `stop→END`、`get_state_history`（P1 回退）；
- `src/math_agent/routing.py`：`after_model_code_consistency` 门禁路径与重试/停机计数；
- `src/math_agent/state.py`：状态字段（核实门禁计数器是否存 state，还是模块级/诊断文件）；
- `src/math_agent/nodes/model_code_consistency.py`、`nodes/coder.py`：门禁逻辑与 output_validation（G8 守卫在此类校验内）；
- `src/math_agent/progress.py`、`insights/`：run 产物与观察面；
- `tests/test_graph_gate.py`、`tests/test_cli.py`：既有门禁 stop/recover 语义测试（P1 在此扩展）。

## 六、约束（CLAUDE.md 红线）

- 质量门禁不得绕过：`restart` 仅重执行合法节点 + 人工判定；final 必须反映实际执行路径（restarted/revised 可审计）；
- CLI/Web/公开状态字段向后兼容；调整 Python 后 Windows 验证 `uv sync` 与 `math-agent supervise --help`；
- checkpoint/旧 run 兼容：无 pause/restart 行为的旧路径逐字节不变；
- 修复后跑与风险相称的测试；涉 run 的改动需真跑验证（mcm51-b 重跑时顺带验证 P0；P1 可构造人为门禁停机场景）。

## 七、执行顺序

P0 → P1（共享 checkpoint/状态工具，但互不阻塞，可并行设计）；完成后：README 批次索引勾状态、00 更新记录补一行、真跑验证。

## 更新记录

- 2026-08-21 建立（评估结论：P0 0.5–1 天 / P1 1–2 天；不阻塞 mcm51-b 重跑）。
- 2026-08-21 追加修复（mcm51-b restart 首次真跑实证）：`restart` 是前台进程，不写 supervisor.json
  → watch/status 显示旧 worker 的过期状态且不跟随。修复：`restart` 自注册监督状态（supervisor.py 新增
  `write_supervisor_state`；cli.py restart 启动时写 running+pid+心跳线程，结束按 checkpoint 判定
  paused/stopped/终态，异常写 blocked+failure.json）。recover（前台）同类问题暂不改，走 supervise-recover。
