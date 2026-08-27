# pilot 模式与早期反证（主线工作项 4 · v2 新增）

- 建立日期：2026-08-21
- 状态：**待设计**（主线第 4 步；必须落在第一次真跑之前，且之后每次真跑强制前置）
- 目标：把「错了回源头改 brief 重跑」（原则 8）的前提——错误被**早而便宜**地发现——做成常规能力：
  跑到 **coder 首轮 execute 出数即停**，产出一页简报（关键数值、单位口径、与题面数据对账、
  每问方向一句话），人（或外部强模型）确认后放行全跑。成本约为全跑 1/10（停在 54 万 tokens 链路前段）。
- 依据：H07 检查点 2（原排在盲测条件④，2026-08-21 提前为常规能力）；
  外部评估 2026-08-21：「开始没考虑清楚就跑偏」是首要失败模式，pilot 是最直接防御。
- 简报模板见 [docs/brief-playbook.md](..\brief-playbook.md) 附录 A。

---

## 一、设计

1. **CLI**：`run --pilot`（或 `supervise --pilot`）：正常启动，在 **coder 首轮 execute 成功后、
   model_code_consistency 之前**落 checkpoint 并停止（复用门禁 stop 语义：checkpoint `next=()`；
   实现时核对 `routing.py` coder→consistency 边，以最小 diff 加条件停止）。
2. **pilot 简报生成**：脚本（纯函数聚合，不调 LLM，模式同 `scripts/run_cost_summary.py` /
   `sample_brief_direction.py`）从 run 产物（code stdout / state / brief 副本）抽取：
   - 关键数值：stdout `RESULT:` 行与主结果数值；
   - 单位口径：数值后的单位标注清单（供人肉眼看应力/力矩、kN/N、秒/分钟混比）；
   - 题面对账表：题面给定数据/交付表格式 vs 代码输出（如 mcm51-b 表 1～表 5 能否填出）；
   - 每问方向一句话：brief `per_question_direction` vs blueprint/代码实际方向（标记偏离）。
3. **放行 / 打回**：
   - 放行：`recover`/`supervise-resume` 续跑（沿用 checkpoint；B05 语义：恢复不接受 `--brief`）；
   - 打回：回源头改 brief 重跑（新 `--out`，原则 8）。
4. **与 M3 的关系**：若 M3（红线机器化）已落地，简报附 `redline_rules` 违规检查结果；未落地前人工核对。

## 二、验收与测试

- 单测：pilot 停止点 checkpoint 语义（`next=()`、recover 可续跑，复用 `tests/test_graph_gate.py` 模式）；
  pilot 简报渲染纯函数（mock state/stdout，参数化）。
- 真跑：mcm51-b 首次全跑前必经 pilot；pilot 阶段成本单独记录进 `cost_summary.md`
  （对账「约全跑 1/10」的假设，为后续成本模型留数据）。

## 三、边界

- **不新增图节点 / 不新增 LLM 评审**（设计红线）；停止语义复用既有门禁 stop 路径。
- 只对「真跑」强制 pilot；`--dry-run` 仍零烧钱。
- 简报只是「人看的反证材料」，不是自动门禁——放行/打回决定权始终在人（副驾驶路线定位）。
- 手工剧本替代（CLI 未落地前）：跑到 coder 首轮 execute 后人工停止进程、人工核对 stdout
  与方向（成本略高、效果等价），对应 00 演练缺口 G6。

## 四、门禁停机与续跑语义（2026-08-21 mcm51-b 实证）

- **实证**：首次 run 因守卫误杀（G8）在 model_code_consistency 无主证据 6 轮停机；`recover` 实测
  **空转**（打印 "recovered." 但 next=() 无节点可续，trace/progress 零新增）——这是刻意的机制设计
  （B05：门禁 stop 后 checkpoint `next=()`，防止带病前进继续烧预算），系统提示「不要 recover」。
- **后果**：修根因（代码/prompt）后只能全新 run，36 万 tokens 无产物。
- **机制改进建议（后续评估，不阻塞本轮）**：给「无主证据停机」增加**人工判定后放行重试 coder** 的路径
  ——人工确认守卫/方向没问题后，把 checkpoint next 指回 coder 重试（仅当门禁停机、非崩溃）；
  这能把守卫误杀类问题从「烧整轮」降为「重试一次」。与 pilot 互补：pilot 管「跑之前/之中早发现」，
  此路径管「门禁停机后的低成本重试」。
- **教训回填**：确定性守卫（M3 红线机器化）校验要落在**语义**上，不能只看指标名（total_cost 通用名
  误杀即实证）。
