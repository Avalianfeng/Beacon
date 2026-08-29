<!-- doc: type=log status=active updated=2026-08-29 -->
# 2026-08-29 ACT-04 evaluation 死分支关账

- 用户拍板：不假设 scoring_notes 存在；删 SYSTEM 条件承诺，保留 D-022 接线。
- 代码：`prompts/evaluation.py` SYSTEM 第 4 条改为恒查「交付物齐备性」；`brief=state.brief` + `render_slice("evaluation")` 不动。
- 文档：后续行动清单 ACT-04 行、D-022 ADR 关联、07/图景 02/current 交叉引用。
- 验收：`pytest tests/test_brief.py::test_evaluation_and_paper_critic_prompts_include_scoring_notes` 1 passed。
- 未 commit。
