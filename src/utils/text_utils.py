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


def split_sentences(text: str) -> list[str]:
    """按中英文句末标点与换行拆分文本"""
    if not text:
        return []
    parts = re.split(r"[。！？!?]+|\n+", text)
    return [part.strip() for part in parts if part.strip()]


def dialogue_length(text: str) -> int:
    """计算文本中对话内容的总长度"""
    if not text:
        return 0
    total = 0
    chinese_corner_quotes = re.findall(r"「(.*?)」", text, flags=re.DOTALL)
    total += sum(len(q) for q in chinese_corner_quotes)
    left_quote = chr(0x201C)
    right_quote = chr(0x201D)
    chinese_double_quotes = re.findall(f"{left_quote}(.*?){right_quote}", text, flags=re.DOTALL)
    total += sum(len(q) for q in chinese_double_quotes)
    ascii_double_quotes = re.findall(r'"(.*?)"', text, flags=re.DOTALL)
    total += sum(len(q) for q in ascii_double_quotes)
    single_quotes = re.findall(r"'(.*?)'", text, flags=re.DOTALL)
    total += sum(len(q) for q in single_quotes)
    return total


def tokenize_words(text: str) -> list[str]:
    """调用项目统一分词器"""
    from src.preprocess.tokenize import tokenize

    return tokenize(text)
