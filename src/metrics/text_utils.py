from __future__ import annotations

import re


def split_sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"[。！？!?]+|\n+", text)
    return [part.strip() for part in parts if part.strip()]


def dialogue_length(text: str) -> int:
    """
    计算文本中对话内容的总长度

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: 初始实现
    说明: 统计四种引号格式中的对话内容长度

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: 修复 dialogue_ratio 全为 0 的问题
    修改内容: 修复 Unicode 转义字符未正确解析的问题，使用 chr() 函数生成 Unicode 字符
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
    from src.preprocess.tokenize import tokenize

    return tokenize(text)
