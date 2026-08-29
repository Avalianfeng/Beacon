<!-- doc: type=plan status=active updated=2026-08-29 -->
# 验证区（docs/验证/）

> **目的**：为「后续重新跑验证」与「检查留痕」提供依据——每次大改造落地后，把该跑的验证内容集、基线结果、记录方式沉淀在这里，避免改造完成后验证面遗忘、结果无据可查。

## 用法

1. **改造落地后**：新建 `验证集-YYYY-MM-DD-改造名.md`（六态 frontmatter），列出分层验证项（单元/CLI 冒烟/真实 LLM/操作面/文档治理）+ 每条命令 + 预期 + 实施时基线。
2. **跑验证时**：按验证集逐项执行；结果在 `运行记录-YYYY-MM-DD.md` 追加（`Add-Content`，六态 frontmatter；文件内按「日期 | 验证集 | 项 | 结果 | 产物路径 | 备注」记录）。
3. **回归触发**：任何大改造（D-0xx）落地、或跨周未跑真实冒烟时，先读最近的验证集，按「第二层 CLI 冒烟（可脚本化）→ 第三层真实 LLM 冒烟」顺序补跑。

## 索引

| 文件 | 覆盖改造 | 状态 |
|---|---|---|
| [验证集-2026-08-29-D022-D023.md](验证集-2026-08-29-D022-D023.md) | D-022 brief 硬信号 + D-023 重试哲学 | 待跑（含实施时基线） |
| 运行记录-*.md | 实际执行结果 | （按需创建） |

## 基线速查

- D-022 验收（实施时已跑）：`test_brief/test_routing/test_insight/test_ops_review/test_ops_handoff/test_coder_baseline/test_cli/test_restart` → **166 passed**
- D-023 验收（实施时已跑）：`test_routing/test_restart/test_pause/test_graph_gate/test_cli/test_coder/test_graph_smoke/test_llm` → **141 passed**
- 全量基线：`.venv\Scripts\python.exe -m pytest -q`（历史 843+，D-022/D-023 后待重新实测全量）

## 相关文档

- 改造详情：`docs/adr/D-022-brief硬信号与schema-v2.md`、`docs/adr/D-023-重试哲学一次停.md`
- 探查全貌：`全流程分析/brief真实调用检查.md`（+ `全流程分析/brief检查/01–06`）
- 文档治理：`docs/文档治理约定.md`（本区文件带六态 frontmatter，README 索引防孤儿）
