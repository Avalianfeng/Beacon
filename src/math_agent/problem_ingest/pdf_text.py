"""PDF/文本层抽取：上标还原、Symbol 字体映射、表格 Markdown。"""
from __future__ import annotations

from pathlib import Path


def sanitize_text(s: str) -> str:
    """剥掉 lone-surrogate / NUL 等 utf-8 不能编码的字符。"""
    if not s:
        return s
    return s.encode("utf-8", errors="ignore").decode("utf-8")


def normalize_math_text(text: str) -> str:
    """规范化 LaTeX PDF 提取的数学文本。"""
    text = text.replace("̸=", "≠")
    text = text.replace("̸<", "≮")
    text = text.replace("̸>", "≯")
    text = text.replace("̸≤", "≰")
    text = text.replace("̸≥", "≱")
    text = text.replace("̸∼", "≄")
    text = text.replace("̸≈", "≇")
    text = text.replace("\u00b5", "\u03bc")
    return text


_SYMBOL_FONT_MAPS = {
    "SymbolMT": {
        "\uf03d": "=", "\uf02d": "-", "\uf02b": "+", "\uf02f": "/",
        "\uf020": " ", "\uf0d7": "\u00d7", "\uf0b4": "\u2032",
        "\uf0b0": "\u00b0", "\uf070": "\u03c0", "\uf061": "\u03b1",
        "\uf062": "\u03b2", "\uf067": "\u03b3", "\uf071": "\u03b8",
        "\uf06c": "\u03bb", "\uf06d": "\u03bc", "\uf073": "\u03c3",
        "\uf045": "\u2208", "\uf05e": "\u222b", "\uf0d5": "\u221e",
        "\uf0d6": "\u2211",
    },
}
_SYMBOL_FONT_MAPS["Symbol"] = _SYMBOL_FONT_MAPS["SymbolMT"]


def map_symbol_font(text: str, font: str) -> str:
    """映射 SymbolMT 等 PUA 字体的字符到标准 Unicode。"""
    for font_prefix, char_map in _SYMBOL_FONT_MAPS.items():
        if font.startswith(font_prefix):
            return "".join(char_map.get(c, c) for c in text)
    return text


def extract_page_with_superscripts(page) -> str:
    """提取页面文本，处理上标和公式排序。"""
    blocks = page.get_text("dict")["blocks"]
    lines_out = []
    for block in blocks:
        all_spans = []
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span["text"]
                if not t.strip():
                    continue
                font = span.get("font", "")
                size = round(span["size"], 1)
                x0 = span["bbox"][0]
                t = map_symbol_font(t, font)
                all_spans.append({"text": t, "font": font, "size": size, "x0": x0})
        if not all_spans:
            continue

        formula_spans = [
            s for s in all_spans if "Symbol" in s["font"] or "Italic" in s["font"]
        ]
        is_formula = len(formula_spans) > 0 and len(all_spans) > 3

        if is_formula:
            formula_only = [
                s for s in all_spans
                if "SimSun" not in s["font"] and "SimHei" not in s["font"]
            ]
            if formula_only:
                baseline_size = max(
                    set(s["size"] for s in formula_only),
                    key=lambda sz: sum(1 for s in formula_only if s["size"] == sz),
                )
            else:
                baseline_size = max(
                    set(s["size"] for s in all_spans),
                    key=lambda sz: sum(1 for s in all_spans if s["size"] == sz),
                )
            all_spans.sort(key=lambda s: s["x0"])
            parts = []
            for s in all_spans:
                if s["size"] < baseline_size - 1.5:
                    parts.append(f"^{{{s['text']}}}")
                else:
                    parts.append(s["text"])
            lines_out.append("".join(parts))
        else:
            for line in block.get("lines", []):
                spans = [s for s in line.get("spans", []) if s["text"].strip()]
                if not spans:
                    continue
                sizes = [round(s["size"], 1) for s in spans]
                baseline_size = max(set(sizes), key=sizes.count)
                parts = []
                for span in spans:
                    text = map_symbol_font(span["text"], span.get("font", ""))
                    size = round(span["size"], 1)
                    if size < baseline_size - 1.5:
                        parts.append(f"^{{{text}}}")
                    else:
                        parts.append(text)
                lines_out.append("".join(parts))
    return "\n".join(lines_out)


def extract_tables_as_markdown(path: Path) -> str:
    """用 pdfplumber 提取表格，渲染为 Markdown 表格文本。"""
    try:
        import pdfplumber
    except ImportError:
        return ""
    tables_md = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table or len(table) < 2:
                    continue
                rows = [[(c or "").replace("\n", " ").strip() for c in row] for row in table]
                rows = [r for r in rows if any(c for c in r)]
                if len(rows) < 2:
                    continue
                max_cols = max(len(r) for r in rows)
                if max_cols < 2:
                    continue
                for r in rows:
                    while len(r) < max_cols:
                        r.append("")
                header = rows[0]
                md = "| " + " | ".join(header) + " |"
                md += "\n|" + "|".join("---" for _ in header) + "|"
                for row in rows[1:]:
                    md += "\n| " + " | ".join(row) + " |"
                tables_md.append(md)
    if not tables_md:
        return ""
    return "\n\n# 提取的表格\n\n" + "\n\n".join(tables_md)


def extract_pdf_text(path: Path, *, include_tables: bool = False) -> tuple[str, int]:
    """抽取 PDF 全文；返回 (text, page_count)。"""
    path = Path(path)
    try:
        import fitz  # pymupdf
        doc = fitz.open(str(path))
        raw = "\n\n".join(extract_page_with_superscripts(page) for page in doc)
        total_pages = len(doc)
        doc.close()
    except ImportError:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        raw = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        total_pages = len(reader.pages)
    text = normalize_math_text(sanitize_text(raw))
    if include_tables:
        tables_md = extract_tables_as_markdown(path)
        if tables_md:
            text = text + tables_md
    return text, total_pages
