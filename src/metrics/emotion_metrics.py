"""
情感密度计算模块

计算文本的情感密度指标




"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .lexicon_metrics import count_mixed_hits, count_weighted_hits, get_emotion_spans
from .text_utils import tokenize_words


def load_negation_words(filepath: str = "data/lexicons/negation_words.txt") -> set[str]:
    """
    加载否定词表

    从文件加载否定词集合，跳过注释行和空行

    参数:
        filepath: 否定词表文件路径

    返回:
        set[str]: 否定词集合
    """
    negation_words: set[str] = set()
    path = Path(filepath)
    if not path.exists():
        return negation_words

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            negation_words.add(line)
    return negation_words


def find_negation_context(text: str, emotion_pos: int, negation_words: set[str], window: int = 3) -> bool:
    """
    检测情感词前是否存在否定词

    在情感词前 window 个字符范围内检测是否存在否定词

    参数:
        text: 原始文本
        emotion_pos: 情感词在文本中的起始位置
        negation_words: 否定词集合
        window: 否定词窗口大小（前N个字），默认3

    返回:
        True 如果存在否定词
    """
    if emotion_pos <= 0 or not negation_words:
        return False

    start = max(0, emotion_pos - window)
    prefix_text = text[start:emotion_pos]

    for neg_word in negation_words:
        if neg_word in prefix_text:
            neg_start = prefix_text.rfind(neg_word)
            neg_end = neg_start + len(neg_word)
            if neg_end >= len(prefix_text) - window:
                return True
            if neg_start <= len(prefix_text) - len(neg_word):
                return True
    return False


def count_negations_before(text: str, emotion_pos: int, negation_words: set[str], window: int = 6) -> int:
    """
    统计情感词前的否定词数量

    在情感词前 window 个字符范围内统计否定词出现次数，用于双重否定检测

    参数:
        text: 原始文本
        emotion_pos: 情感词在文本中的起始位置
        negation_words: 否定词集合
        window: 否定词窗口大小（前N个字），默认6

    返回:
        否定词数量（0, 1, 2, ...）
    """
    if emotion_pos <= 0 or not negation_words:
        return 0

    start = max(0, emotion_pos - window)
    prefix_text = text[start:emotion_pos]

    count = 0
    for neg_word in negation_words:
        pos = 0
        while True:
            idx = prefix_text.find(neg_word, pos)
            if idx < 0:
                break
            count += 1
            pos = idx + len(neg_word)
    return count


def lexical_sentiment_density(
    text: str,
    pos_terms: Mapping[str, float],
    neg_terms: Mapping[str, float],
    negation_words: set[str] | None = None,
    enable_negation: bool = True,
) -> dict[str, float]:
    """
    计算词汇情感密度（支持否定词翻转和加权计数）

    使用 phrase 模式匹配，支持：
    - token 级匹配（如"快乐"）
    - 子串匹配（如"冷笑"被分词为"冷"+"笑"时仍能匹配）
    - 否定词翻转：单重否定翻转极性，双重否定还原极性
    - 加权计数：支持带权重的词典（如"心花怒放"权重为 3）

    参数:
        text: 原始文本
        pos_terms: 正面情感词表，格式为 {词条: 权重}
        neg_terms: 负面情感词表，格式为 {词条: 权重}
        negation_words: 否定词集合，如果为 None 则自动加载
        enable_negation: 是否启用否定词翻转，默认 True

    返回:
        dict[str, float]: 包含 pos_density, neg_density, net_density





    """
    if not text:
        return {"pos_density": 0.0, "neg_density": 0.0, "net_density": 0.0}

    tokens = tokenize_words(text)
    total_tokens = max(len(tokens), 1)

    if not enable_negation:
        pos = count_weighted_hits(text, tokens, pos_terms) / total_tokens
        neg = count_weighted_hits(text, tokens, neg_terms) / total_tokens
        return {"pos_density": pos, "neg_density": neg, "net_density": pos - neg}

    if negation_words is None:
        negation_words = load_negation_words()

    pos_spans = get_emotion_spans(text, tokens, pos_terms.keys())
    neg_spans = get_emotion_spans(text, tokens, neg_terms.keys())

    pos_count = 0.0
    neg_count = 0.0

    for start, _end, term in pos_spans:
        weight = pos_terms.get(term, 1)
        negation_num = count_negations_before(text, start, negation_words)
        if negation_num % 2 == 1:
            neg_count += weight
        else:
            pos_count += weight

    for start, _end, term in neg_spans:
        weight = neg_terms.get(term, 1)
        negation_num = count_negations_before(text, start, negation_words)
        if negation_num % 2 == 1:
            pos_count += weight
        else:
            neg_count += weight

    pos_density = pos_count / total_tokens
    neg_density = neg_count / total_tokens

    return {"pos_density": pos_density, "neg_density": neg_density, "net_density": pos_density - neg_density}


def pos_neg_ratio(text: str, pos_terms: dict[str, int], neg_terms: dict[str, int]) -> float:
    """
    计算正负情感词比例


    """
    if not text:
        return 0.0
    tokens = tokenize_words(text)
    pos = count_mixed_hits(text, tokens, pos_terms.keys())
    neg = count_mixed_hits(text, tokens, neg_terms.keys())
    if pos == 0:
        return 0.0
    return pos / max(neg, 1)
