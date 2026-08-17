"""供 coder/sensitivity prompt 共用的数据文件路径提示。"""
from __future__ import annotations
from functools import lru_cache
import json
import os
from pathlib import Path


def _frame_profile(frame, *, prefix: str) -> str:
    selected = list(frame.columns[:12])
    dtypes = {str(column): str(frame[column].dtype) for column in selected}
    # 窄表（≤4 列，典型为竖排“参数名称/工况取值”键值表）只给 2 行样例时，模型看不到
    # 大部分参数名，会按近似名字做严格查找导致崩溃（锚杆题 6 批全挂在此类问题）；窄表多给几行。
    narrow = len(frame.columns) <= 4
    sample_rows = 10 if narrow else 2
    sample_columns = selected[:8]
    samples = []
    for record in frame.loc[:, sample_columns].head(sample_rows).to_dict(orient="records"):
        samples.append({str(key): str(value)[:80] for key, value in record.items()})
    return (
        f"\n  {prefix}: columns="
        + json.dumps([str(column) for column in selected], ensure_ascii=False)
        + "; dtypes=" + json.dumps(dtypes, ensure_ascii=False)
        + f"; 前{sample_rows}行样例=" + json.dumps(samples, ensure_ascii=False)
    )


@lru_cache(maxsize=64)
def _profile_file(path_text: str, file_type: str, mtime_ns: int) -> str:
    """读取真实表头、dtype 和两行样例；mtime 参与缓存键，文件变化后自动失效。"""
    del mtime_ns  # 仅用于缓存失效
    try:
        import pandas as pd

        path = Path(path_text)
        if file_type in ("xlsx", "xls"):
            book = pd.ExcelFile(path)
            parts = [
                f"\n  共 {len(book.sheet_names)} 张工作表: "
                + json.dumps(list(book.sheet_names), ensure_ascii=False)
                + "。必须逐表读取（sheet_name=工作表名 或 ExcelFile.sheet_names），"
                "禁止只读默认第一张表。"
            ]
            for sheet in book.sheet_names[:8]:
                # nrows 至少 12：窄表（竖排参数表）可能只有 2--4 列但参数名有十几行，
                # 只读 3 行会让模型看不到大部分参数名而按近似名查找崩溃。
                # 展示行数由 _frame_profile 按表宽裁剪，宽表仍只展示 2 行样例。
                frame = pd.read_excel(book, sheet_name=sheet, nrows=12)
                parts.append(_frame_profile(frame, prefix=f"工作表 {sheet!r}"))
            return "".join(parts)
        if file_type == "csv":
            frame = pd.read_csv(path, nrows=3)
            return _frame_profile(frame, prefix="真实读取契约")
        return ""
    except Exception as exc:
        return f"\n  运行时数据画像不可用: {type(exc).__name__}"


def build_data_hint(data_dir: str | None, data_files: list) -> str:
    """构造数据文件路径提示文本。

    data_files: list[DataFileInfo]，需要有 .filename / .file_type / .path 属性。
    """
    if not data_dir or not data_files:
        return ""
    safe_data_dir = Path(data_dir).as_posix()
    lines = [f"数据目录（可直接交给 pathlib.Path）: {safe_data_dir}"]
    for df in data_files:
        fp = os.path.join(data_dir, df.path) if not os.path.isabs(df.path) else df.path
        fp = Path(fp).as_posix()
        summary = df.summary or {}
        columns = summary.get("columns", [])
        if isinstance(columns, list) and columns:
            schema = f"；实际列名: {', '.join(map(str, columns[:20]))}"
        else:
            schema = ""
        rows = summary.get("rows")
        if isinstance(rows, (int, float)):
            schema += f"；约 {int(rows)} 行"
        if df.file_type in ("xlsx", "xls"):
            sheets = summary.get("sheets")
            if isinstance(sheets, list) and sheets:
                names = [str(item.get("name", "")) for item in sheets if isinstance(item, dict)]
                names = [name for name in names if name]
                if names:
                    schema += f"；工作表: {', '.join(names[:12])}"
            lines.append(f"- {fp} (Excel, 用 pd.read_excel 读取{schema})")
        elif df.file_type == "csv":
            lines.append(f"- {fp} (CSV, 用 pd.read_csv 读取{schema})")
        elif df.file_type == "pdf":
            lines.append(f'- {fp} (PDF, 需用 pymupdf 提取文本: import fitz; doc=fitz.open(r"{fp}"); text="\\n".join(p.get_text() for p in doc))')
        elif df.file_type == "docx":
            lines.append(f"- {fp} (Word, 需用 python-docx 读取)")
        else:
            lines.append(f"- {fp} (文本文件)")
        local_path = Path(fp)
        if local_path.is_file() and df.file_type in ("xlsx", "xls", "csv"):
            lines.append(_profile_file(
                str(local_path), df.file_type, local_path.stat().st_mtime_ns,
            ))
    return (
        "\n# 可用数据文件\n" + "\n".join(lines) + "\n"
        "请优先读取这些真实数据进行计算，不要编造 mock 数据。\n"
        "必须按上面列出的实际列名读取，不得猜测‘经度/纬度’等不存在的字段。\n"
        "Excel 若含多张工作表，必须按上面列出的全部工作表逐表读取，禁止只读默认第一张表。\n"
        "若附件含跨表客户主键，必须按各表真实列名显式映射为内部 customer_id；"
        "不得假设所有表使用同一个原始列名。\n"
        "时间窗若为 HH:MM 字符串，必须先转换为从 0:00 起的分钟或小时数，再与到达时间比较。\n"
        "Excel 分组表的分组标识列（如“锚杆直径”）可能只在每组首行填写、后续行缺失——"
        "处理前先检查缺失值分布，需要时用前向填充（ffill）补全后再按组聚合。\n"
        "禁止把清理前的原始 DataFrame 直接 print 到 stdout：缺失值会显示为 NaN，"
        "触发共享输出校验（非有限数值）拒绝整段 stdout——即使 RESULT 行全部是有限值。"
        "调试打印前必须先 ffill/dropna 清理，或只打印清理后的数据。\n"
        "若对列名做清理（去掉换行/空格等），必须以清理后的实际列名（先 print(df.columns.tolist())"
        "核对）为准，禁止凭记忆混用清理前/后的两种写法（如把 '预紧力矩 T \\n/N·m' 清理后"
        "误写成 '预紧力矩T/N·m'）。\n"
        "竖排键值表（列名含“参数名称”/“工况”且每行一个参数）的第一列是参数名，"
        "必须以数据提示中出现的名字**逐字**匹配；缺失的可选参数使用题面给定值或显式注释的"
        "工程默认值，不得按近似名字查找后中断整个脚本。\n"
        "Windows 路径统一使用上面的正斜杠形式或 pathlib.Path；"
        "不要创建以单个反斜杠结尾的 raw string（会导致 SyntaxError）。\n"
    )


def build_data_summary_hint(data_files: list) -> str:
    """构造数据摘要提示文本（供 analyst 用，不含绝对路径）。"""
    if not data_files:
        return ""
    lines = []
    for df in data_files:
        line = f"- {df.filename} ({df.file_type})"
        summary = df.summary or {}
        if "sheets" in summary:
            for s in summary["sheets"][:5]:
                cols = ", ".join(s.get("columns", [])[:8])
                lines.append(f"  └ {s['name']}: {s.get('rows',0)}行×{s.get('cols',0)}列 [{cols}]")
        elif "text_excerpt" in summary:
            excerpt = summary["text_excerpt"][:200].replace("\n", " ")
            lines.append(f"  └ 文本摘录: {excerpt}...")
            pq = summary.get("parse_quality") or {}
            method = pq.get("method")
            if method:
                warn = pq.get("warnings") or []
                flag = "需核对" if (pq.get("ok") is False or warn) else "可用"
                lines.append(f"  └ 解析质量: {method} · {flag}")
        lines.append(line)
    return (
        "\n# 附件数据概况\n已有以下数据文件可用：\n" + "\n".join(lines) + "\n"
        "请在 data_requirements 中将对应字段标注为 given，并在建模路线中考虑如何使用这些真实数据。\n"
    )
