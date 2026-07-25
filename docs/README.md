# Beacon 文档索引与当前状态

最后核对：2026-07-25。

## 当前结论

`runs/green-logistics-rootfix-v4-20260717` 仍是完整公开 CLI 闭环的基准运行；入口为
`math-agent start`，调用链经过 supervisor、checkpoint recover、全部 LangGraph 节点、runner、
结果校验、writer、LaTeX 和 finalizer。针对 `runs/wodecesium` 暴露出的“总计 10 页、正文只有
8 页”问题，现行实现同时强化篇幅质量门禁和实质实验生成。未使用 `scripts/repair_final_run.py`，
未修改原始附件，也未放宽 120 秒脚本期限、2 GB 内存限制或既有数值质量门槛。

现行默认门禁要求 PDF 在附录前至少有 20 个非空正文页，且正文至少有 15000 个非空白字符；两个
阈值可分别通过 `MATH_AGENT_MIN_PAPER_BODY_PAGES` 与 `MATH_AGENT_MIN_PAPER_BODY_CHARS` 配置。
门禁不通过时 finalizer 必须把运行标记为 degraded，并给出实际页数或字符数，不能把附录代码页、
空白页或重复段落当成正文篇幅。

最终证据如下：

- `completion.json.status=completed`，issues/warnings 均为空；checkpoint 无下一节点。
- supervisor PID 22708、worker PID 3004 及其 transport 后代均已退出；公开 `status` 返回 completed。
- LLM trace 共 67 个逻辑调用、83 个物理 attempt；真实出现 3 次 120 秒 timeout、3 次 server error，
  其中两次 long 请求约 234 秒后切换上游成功。run-scoped 模型冷却状态可跨恢复 worker 继承。
- 主方案真实读取订单、距离矩阵、时间窗和坐标四个附件，RESULT 为成本 144586.99 元、车辆
  159 辆、服务率 1.0000、碳排放 14634.14 kg。
- 三个有效基线、三组非空敏感性；模型—代码一致性 8、论文评审 8、综合评分 7.1。
- 完整 CLI 基准运行的两遍 XeLaTeX 均 exit 0，历史产物为 9 页；该产物证明调用链闭环，不再代表
  现行论文篇幅验收标准。
- `runs/wodecesium-lengthfix-v3-20260717` 是从 `wodecesium` 已验证 checkpoint 状态进行的独立、
  确定性论文再生成验证，不是一次新的全流程求解。该运行是篇幅门禁的早期回归证据。
- `runs/wodecesium-content-optimized-final-v2-20260717` 是当前内容增强参考稿，同样不是新的完整
  CLI 闭环。它通过正式主方案数值、四附件数据血缘、三类基线、深度实验和篇幅门禁；PDF 共
  31 页，正文 25 页、25057 个非空白字符，附录从第 30 个物理页开始。全部 31 页已渲染检查，
  无乱码、裁切、重叠或严重横向溢出。
- 当前 Python 回归为 591 passed / 4 skipped；Web UI 回归为 16/16。Windows 环境已验证
  `uv sync` 可直接安装 LiteLLM 1.91.0，且 `math-agent supervise --help` 可正常启动。

系统并不承诺外部上游永远不出现 502、429、断连或超时；“已解决”的含义是这些故障现在受
单次/总硬期限、错误分类、worker 回收、跨 worker 熔断、同节点恢复上限和 checkpoint 定点恢复
约束，不再无限挂起、无限重试或污染正式结果。

## 恢复入口与本地环境约束

Web UI 仅在任务状态为 `failed` 且存在 checkpoint 时显示“从最近检查点恢复”。确定性配置错误
会进入 `blocked`；修正配置后使用 `math-agent recover --out <run-dir> --thread <thread>` 从原
checkpoint 续跑。`human_review` 的批准或拒绝仍使用 `resume`/`supervise-resume`，不能由恢复按钮
代替。

当前支持 Python 3.11--3.13，并固定 LiteLLM 1.91.0，确保 Windows 能直接安装 wheel，不依赖
Visual Studio C++ linker。OpenAI 兼容路由的模型名必须使用 `openai/<model>` 格式；仅配置
`OPENAI_API_BASE` 不能让 LiteLLM 从裸模型名推断 provider。示例配置、README 与 Web 保存逻辑
必须保持这一约束一致。

Web UI 首次访问按环境检查、服务商选择、密钥填写、模型验证和配置保存完成初始化；进入工作台后，
主流程收敛为“导入题目 → 确认题目 → 启动生成”。模型连接测试直连用户填写的 OpenAI 兼容端点，
因此会先移除 `openai/`、`ollama/` 等 LiteLLM 传输前缀，再发送厂商原生模型名；保存到 `.env`
时仍使用 `provider/model`，测试协议与正式运行协议不能混为一谈。

## 为什么旧 PDF 只有 8--10 页，当前如何保证 20 页正文

`runs/wodecesium/paper.pdf` 共 10 页，附录从第 9 页开始，实际正文只有 8 页、6472 个非空白字符；
这不是 XeLaTeX 截断。根因有两层：绿色物流安全分支绕过 writer LLM，直接返回一组偏短的固定章节；
finalizer 又只检查编译、评分和证据质量，没有检查附录前的正文页数与内容量。通用 writer 还会把模型
与敏感性章节替换成绿色物流固定文本，导致提示词中的篇幅要求既不可执行，也可能污染其他题目。

现行 writer 为特殊安全分支补齐问题分析、数据预处理、假设依据、数学模型、分问题求解、基线对比、
复杂度、敏感性、误差边界和部署建议，并只引用已验证 RESULT、BREAKDOWN 与敏感性数组。安全求解器
还执行路线内 2-opt、200 个固定路线随机交通情景、客户/线路级服务诊断，以及订单取消、新增订单、
地址变更、时间窗收紧和车辆故障五类独立动态事件。地址或时间窗变化先移除旧任务再唯一回插；随机
情景完整重算等待、晚到、能耗和碳成本，不再用标签或局部成本冒充深度证据。通用题目的
七个章节组全部交给当前题目的 writer 生成；每组有非空白字符预算，首次过短会带着质量问题重写一次，
再次不足则保留 checkpoint 并失败，不能用其他题目的固定稿兜底。最终 PDF 还需通过 20 个非空正文页
和 15000 个正文字符的双门禁。

当前参考稿页数来自新增的论证链、真实对照和实验解释，不是通过放大字号、空白页、复制段落或延长
代码附录获得。参考重建脚本会拒绝非空输出目录，并在进入 writer/LaTeX 前复用正式数值、深度和附件
血缘门禁，编译后再检查正文页数、非空页和字符量。它不会伪造一次新的 supervisor/checkpoint 流程，
因此不能替代完整 CLI 基准运行的 `completion.json`、paper critic、evaluation 与 human review 证据。

## 现行文档

- [`paper-content-quality.md`](paper-content-quality.md)：20 页正文门禁、深度实验契约、动态事件口径与参考重建。
- [`beacon-resilient-execution.md`](beacon-resilient-execution.md)：后台监督、恢复、硬期限和最终收口。
- [`beacon-full-pipeline-root-cause-20260717.md`](beacon-full-pipeline-root-cause-20260717.md)：完整调用链、
  分项根因、测试矩阵和 v4 真题证据。
- [`llm-timeout-retry-redesign.md`](llm-timeout-retry-redesign.md)：LLM transport、取消和预算机制；
  现行参数以 `.env.example` 与代码为准。
- [`problem-blueprint-implementation-plan.md`](problem-blueprint-implementation-plan.md)：ProblemBlueprint
  落地的历史实施记录。
- [`writer-quality-recovery-development.md`](writer-quality-recovery-development.md)：writer 恢复与质量增强
  的设计记录，包含尚未全部落地的建议。

## 历史方案

`docs/superpowers/plans/` 和 `docs/superpowers/specs/` 保存阶段性计划与设计，不是现行事实源。
旧文件名、旧超时变量和“≥30 页/≥10 图”等声明只按历史上下文阅读。

## 验证入口

```powershell
uv run --extra dev pytest -q
npm.cmd test
uv run math-agent status --out runs/green-logistics-rootfix-v4-20260717 --thread green-logistics-rootfix-v4
uv run python scripts/render_content_optimized_reference.py `
  --source-state runs/verified-run/final_state.json `
  --data-dir runs/verified-run/data `
  --out runs/content-optimized-reference
```

真实运行只有在 completion 摘要校验有效、正式证据门禁通过、LaTeX 两遍编译成功且 PDF 逐页视觉
检查完成后才可验收；“流程走到结尾”本身不算成功。
