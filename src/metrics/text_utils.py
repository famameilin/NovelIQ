from __future__ import annotations

import re
from typing import List


def split_sentences(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"[。！？!?]+|\n+", text)
    return [part.strip() for part in parts if part.strip()]


def dialogue_length(text: str) -> int:
    if not text:
        return 0
    total = 0
    chinese_corner_quotes = re.findall(r"「(.*?)」", text, flags=re.DOTALL)
    total += sum(len(q) for q in chinese_corner_quotes)
    left_quote = "\u201c"
    right_quote = "\u201d"
    chinese_double_quotes = re.findall(f"{left_quote}(.*?){right_quote}", text, flags=re.DOTALL)
    total += sum(len(q) for q in chinese_double_quotes)
    ascii_double_quotes = re.findall(r'"(.*?)"', text, flags=re.DOTALL)
    total += sum(len(q) for q in ascii_double_quotes)
    single_quotes = re.findall(r"'(.*?)'", text, flags=re.DOTALL)
    total += sum(len(q) for q in single_quotes)
    return total


def tokenize_words(text: str) -> List[str]:
    from src.preprocess.tokenize import tokenize

    return tokenize(text)
