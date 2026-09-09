# Beacon 项目协作规则

## 沟通与文档

- 新增或更新项目文档时使用中文；代码标识符、命令和外部专有名词可保留英文。
- 现行用法入口是 `全流程分析/全流程定稿/00-正式闭环.md`。`docs/README.md` 只留产品指针。对外说明以根 `README.md` 为准。历史方案在 `docs/archive/` 与 `全流程分析/archive/`，不得当作当前实现说明。
- 接手 `problems/<题>/` 做题（探索期）：先读题根 `进行状态.md`（活状态单页；会话首读末写；收束后并入 `交接-beacon.md`）。
- **文档治理**：活文档首行带六态 frontmatter（非 `status=active` 不得当现行依据）；流程决策写进定稿 00，不新开 ADR；已进代码的机制不保留 ADR；学-xx 只在 `全流程分析/决策登记.md` 记流水账；过期文档以移入 archive 为主，不在现行目录留第二套说明。审计：`python scripts/audit_docs.py`。
- **工作日志**：进度与结论只写 `docs/log/YYYY-MM-DD-简要说明.md`。只允许 pwsh `Add-Content` 追加；禁止用编辑/写入工具改日志。新文件首行须带六态 frontmatter。旧 `docs/实现计划-8-20/log.md` 已随该目录进入 archive。
- 涉及真实运行结论时，必须同时给出代码、测试或 `runs/` 产物证据，不把“生成了文件”当作成功。

## 实现与验证

- 保持 CLI、Web UI 和公开状态字段向后兼容。
- OpenAI 兼容路由的模型名必须使用 `openai/<model>`；`.env.example` 与 Web 配置归一化必须保持一致。
- 调整 Python 或 LiteLLM 依赖约束后，必须在 Windows 验证 `uv sync` 和 `math-agent supervise --help`。
- LLM、runner、supervisor 和 finalizer 的硬期限、整树回收、数据血缘与质量门禁不得被绕过。
- 不允许硬编码、全零、非法数值、退出码 0 的失败声明或未读取附件的结果进入正式论文。
- `primary`、`baseline`、`supporting` 和临时 attempt 必须保持证据职责隔离。
- 修复后运行与风险相称的测试；论文/PDF 改动还要重新编译、逐页渲染并视觉检查。

## 工作区安全

- 工作区可能包含用户未提交修改；只改任务需要的文件，不覆盖或清理无关改动。
- 不修改原始题目附件，不使用 `scripts/repair_final_run.py` 代替正常流程。
- 删除运行产物、临时文件或历史文档前先征得用户确认。
