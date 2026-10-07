"""关键词 SQL 查询与返回结果匹配共用的 LIKE 通配符语义"""

from __future__ import annotations

import re


def term_matches(term: str, text: str) -> bool:
    """2026-09-04 用于按通配符语义判断词项是否命中文本（与 SQL ILIKE 口径对齐）

    词项里的 % 匹配任意长度、_ 匹配单个字符，其余字符按字面量大小写不敏感匹配；
    无通配符时等价于子串包含。用于 Python 侧内存匹配路径（案例池、事件根视图归并）。
    """
    if not term:
        return False
    regex = "".join(".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in term)
    return re.search(regex, text, flags=re.IGNORECASE | re.DOTALL) is not None


def like_pattern(term: str) -> str:
    """2026-09-04 用于把词项包成 SQL LIKE 模式：前后加 % 做子串，内部 %/_ 保留为通配符"""
    return f"%{term}%"
