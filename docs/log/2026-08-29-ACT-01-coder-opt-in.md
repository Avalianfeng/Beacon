<!-- doc: type=log status=active updated=2026-08-29 -->
# 2026-08-29 ACT-01 coder 重估（D-024 LLM 默认关）

- 学-11 ① 落地：无 T-19 冻结资产时 `coder_generate` 不调 `complete()`；错误串 `coder: LLM generate disabled; register T-19 or --allow-coder-llm`。
- 逃生口：`--allow-coder-llm`（run/start/supervise 转发）+ `MATH_AGENT_ALLOW_CODER_LLM=1`；state `allow_coder_llm`。T-19 与 `CODER_DETERMINISTIC` 不要求旗标。
- 未改：`sensitivity_code_generate`、`MAX_CODE_RETRIES`、`complete()`、ACT-05、注入契约。后续已登记 ACT-14 / ACT-15（清单 + 图景 03 A-17/A-18）。
- 验收：`uv run pytest tests/nodes/test_coder.py tests/nodes/test_frozen_asset.py tests/test_cli.py tests/test_graph_smoke.py tests/test_restart.py tests/test_routing.py tests/test_graph_full_smoke.py tests/nodes/test_writer_recover.py tests/integration/test_granular_recovery.py tests/test_coder_baseline.py` → 150 passed。
