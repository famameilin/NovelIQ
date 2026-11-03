"正文字数统计"

from __future__ import annotations

import re

_ZERO_WIDTH_RE = re.compile("[\ufeff\u200b\u200c\u200d]")
_WHITESPACE_RE = re.compile(r"\s")


def count_words(text: str) -> int:
    "统计非空白字符数，标点计入，换行与空格不计"
    return len(_WHITESPACE_RE.sub("", _ZERO_WIDTH_RE.sub("", text)))
