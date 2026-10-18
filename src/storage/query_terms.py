"""关键词查询与返回结果匹配共用的词项拆分与 LIKE 通配符语义"""

from __future__ import annotations

import re
import unicodedata

_WHOLE_QUERY_MAX_CHARS = 20
_SPLIT_RE = re.compile(r"[\s,，。；;：:、!?！？\"'（）()\[\]{}]+")


def extract_query_terms(query: str, *, max_whole_query_chars: int = _WHOLE_QUERY_MAX_CHARS) -> list[str]:
    """从中英文查询中提取稳定关键词（NFC 归一化 + 小写 + 去重）

    整句原文仅在前缀长度受限时保留为词项；长句只保留拆分词项，
    无分隔符时返回空列表（避免整句 LIKE 全表扫描）。
    """
    normalized = unicodedata.normalize("NFC", query).replace("\r\n", "\n").replace("\r", "\n").strip().lower()
    if not normalized:
        return []
    terms = [term for term in _SPLIT_RE.split(normalized) if term]
    if len(normalized) > max_whole_query_chars:
        if not _SPLIT_RE.search(normalized):
            # 无分隔符时 re.split 退化为整句本身，必须丢弃避免整句 LIKE 扫描
            return []
        return list(dict.fromkeys(terms))
    return list(dict.fromkeys([normalized, *terms]))


def query_search_terms(query: str) -> list[str]:
    """内存检索的词项集（空白/标点拆分、任一命中）

    在 extract_query_terms 之上补整句回退：拆分返回空时把整句当一个字面词项；
    空查询仍返回空列表，由调用方保持"不填不过滤"。
    """
    terms = extract_query_terms(query)
    if terms:
        return terms
    normalized = query.strip()
    return [normalized] if normalized else []


def term_matches(term: str, text: str) -> bool:
    """按通配符语义判断词项是否命中文本（与 SQL ILIKE 口径对齐）

    词项里的 % 匹配任意长度、_ 匹配单个字符，其余字符按字面量大小写不敏感匹配；
    无通配符时等价于子串包含。
    """
    if not term:
        return False
    regex = "".join(".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in term)
    return re.search(regex, text, flags=re.IGNORECASE | re.DOTALL) is not None


def like_pattern(term: str) -> str:
    """把词项包成 SQL LIKE 模式：前后加 % 做子串，内部 %/_ 保留为通配符"""
    return f"%{term}%"
