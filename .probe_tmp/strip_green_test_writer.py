# -*- coding: utf-8 -*-
from pathlib import Path
import ast

p = Path(r"e:\git_clone\Beacon\tests\nodes\test_writer.py")
text = p.read_text(encoding="utf-8")

# 删除文件尾部全部 _verified_* 绿色 writer 测试（从 test_verified_notation... 起到文件尾）
i = text.index("def test_verified_notation_contains_no_control_characters():")
text = text[:i].rstrip() + "\n"

# _state 中的绿色题面改为通用题面
text = text.replace('problem="城市绿色物流配送调度",', 'problem="p",', 1)

ast.parse(text)
p.write_text(text, encoding="utf-8")
print("ok")
