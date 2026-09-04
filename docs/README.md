<!-- doc: type=state status=active updated=2026-09-05 -->
# Beacon 文档中心

**做题与用法**：只读 [`全流程分析/全流程定稿/00-正式闭环.md`](../全流程分析/全流程定稿/00-正式闭环.md)。  
本目录不再维护第二套流程说明书。

| 还活着 | 干什么 |
|---|---|
| [agent协作协议](agent协作协议.md) | 改不改机制时的边界（摘要；正文在定稿 00） |
| [00-体系现状与原则](00-体系现状与原则.md) | 产品定位与原则（短） |
| [current/](current/README.md) | 现在卡在哪 |
| [01](01-论文内容质量与篇幅门禁.md) · [02](02-长流程可靠执行与恢复.md) · [03](03-控制台观察面.md) | 产品机制（闸门 / 恢复 / watch），不是做题顺序 |
| [验证/](验证/README.md) | 验证集 |
| [log/](log/) | 工作日志（只追加） |
| [adr/](adr/README.md) | 默认不写；历史已归档 |
| [archive/](archive/README.md) | 过时全文 |

```powershell
python scripts\audit_docs.py
.venv\Scripts\python.exe -m pytest -q
```
