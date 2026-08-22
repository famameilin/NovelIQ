"""
情感密度计算模块

计算文本的情感密度指标
"""

from __future__ import annotations

from collections.abc import Mapping

from src.utils.text_utils import tokenize_words

from .lexicon_metrics import count_mixed_hits, count_weighted_hits, get_emotion_spans
from .negation import is_flipped, load_negation_spec


def lexical_sentiment_density(
    text: str,
    pos_terms: Mapping[str, float],
    neg_terms: Mapping[str, float],
    spec=None,
    enable_negation: bool = True,
) -> dict[str, float]:
    """计算词汇情感密度（phrase 匹配，2026-08-16 M5 起否定翻转复用 src.metrics.negation，权重 1.0）。"""
    if not text:
        return {"pos_density": 0.0, "neg_density": 0.0, "net_density": 0.0}

    tokens = tokenize_words(text)
    total_tokens = max(len(tokens), 1)

    if not enable_negation:
        pos = count_weighted_hits(text, tokens, pos_terms) / total_tokens
        neg = count_weighted_hits(text, tokens, neg_terms) / total_tokens
        return {"pos_density": pos, "neg_density": neg, "net_density": pos - neg}

    if spec is None:
        spec = load_negation_spec()

    pos_spans = get_emotion_spans(text, tokens, pos_terms.keys())
    neg_spans = get_emotion_spans(text, tokens, neg_terms.keys())

    pos_count = 0.0
    neg_count = 0.0

    for start, _end, _term in pos_spans:
        if is_flipped(text, start, spec):
            neg_count += 1.0
        else:
            pos_count += 1.0

    for start, _end, _term in neg_spans:
        if is_flipped(text, start, spec):
            pos_count += 1.0
        else:
            neg_count += 1.0

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
