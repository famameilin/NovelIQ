"""章节解析前的防御性文本预处理

解析器对输入文本做防御性清洗（去 BOM、统一换行、去零宽空格、合并连续空行），
最终产出的字符偏移一律相对 preprocess_text 的输出；调用方如需按偏移切片，
必须使用同一份预处理后的文本。
"""

from __future__ import annotations

import re

_BOM = "\ufeff"
_FULL_WIDTH_SPACE = "\u3000"
_ZERO_WIDTH_CHARS = ("\u200b", "\u200c", "\u200d")

_LINE_SEPARATOR_RE = re.compile(r"[\u2028\u2029]")
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n+")


def preprocess_text(text: str) -> str:
    """防御性文本预处理（幂等）"""
    if not text:
        return ""
    text = text.replace(_BOM, "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _LINE_SEPARATOR_RE.sub("\n", text)
    text = text.replace(_FULL_WIDTH_SPACE, " ")
    for ch in _ZERO_WIDTH_CHARS:
        text = text.replace(ch, "")
    text = _BLANK_LINE_RE.sub("\n\n", text)
    return text
