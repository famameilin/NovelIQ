from __future__ import annotations

import re


def split_sentences(text: str) -> list[str]:
    """
    按中文/英文句末标点与换行拆分文本

    说明: 从 metrics 专属模块上移为公共文本工具，避免 lexicons 为了 tokenizer 反向依赖 metrics
    """
    if not text:
        return []
    parts = re.split(r"[。！？!?]+|\n+", text)
    return [part.strip() for part in parts if part.strip()]


def dialogue_length(text: str) -> int:
    """
    计算文本中对话内容的总长度

    说明: 从 metrics.text_utils 平移到公共层，供指标与其他文本模块复用
    """
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
    """
    调用项目统一分词器

    说明: 将 tokenizer 入口放到公共层，lexicons 和 metrics 都只依赖 utils
    """
    from src.preprocess.tokenize import tokenize

    return tokenize(text)
