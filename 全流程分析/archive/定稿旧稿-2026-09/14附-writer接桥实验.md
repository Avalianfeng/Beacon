# 14附 · writer 接桥实验（cumcm23-c · D-029）

> 定稿附属 · 2026-09-04 · **实验已跑**

## 做了什么

```text
scripts/exp_writer_bridge_cumcm23c.py
  problem.md + brief.json + evidence.json/q_lines + evidence.md
  + ModelVersion/Assumptions/SensitivityRun（手工适配）
  → writer_node → writer_section ×7
  → runs/cumcm23-c-writer-bridge-full/paper.md
```

不经 coder/modeler；不改 `graph.py`；真 LLM（writer 路由模型）。

## 结果

| 项 | 结果 |
|---|---|
| 大纲 + 全 7 节 | **PASS**（约 3.2 min） |
| 主锚数字 | 命中：12.9643 / 2363.4707 / 3502.5203 / 28 / 438.5931 / 794.6371 |
| `check_paper_numbers` | **21 未溯源**（派生%如 57.8/73.2、截断 1478.8998、文献年、假种子 42） |
| 对照轨 B `paper-prose.md` | 轨 B：449 token **未溯源 0**；writer 稿更长但闸门更松 |

## 结论（给接桥工程）

1. **接桥方向成立**：本地 reference/evidence 可喂进 state，writer 链能独立产出完整 md。  
2. **缺口不在「能不能跑」**，在输入契约：`available_numbers` 只吃 Q/RESULT 行（≤40），派生量/四舍五入/文献年仍会被写进正文。  
3. **轨 B 的 evidence.md 语义化仍要保留**，应变成 writer 白名单的一等输入，而不是只塞进 stdout 附录。  
4. **工程 P0 不变**：`--from writer` + 正式适配器；另加写后 `check_paper_numbers --strict` 进写作完成判据。  
5. 本题应急 `paper-prose.md` 仍可做人评对象；writer 稿作**体系路径验证产物**，勿混成已验收终稿。

## 产物路径

- `runs/cumcm23-c-writer-bridge-full/paper.md`
- `runs/cumcm23-c-writer-bridge-full/experiment_log.md`
- `scripts/exp_writer_bridge_cumcm23c.py`
