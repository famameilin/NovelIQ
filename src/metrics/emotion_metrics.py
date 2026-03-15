from __future__ import annotations

from typing import Dict, Iterable, List

from .lexicon_metrics import count_token_hits
from .text_utils import tokenize_words


def lexical_sentiment_density(text: str, pos_terms: Iterable[str], neg_terms: Iterable[str]) -> Dict[str, float]:
    if not text:
        return {"pos_density": 0.0, "neg_density": 0.0, "net_density": 0.0}
    tokens = tokenize_words(text)
    pos = count_token_hits(tokens, pos_terms) / max(len(tokens), 1)
    neg = count_token_hits(tokens, neg_terms) / max(len(tokens), 1)
    return {"pos_density": pos, "neg_density": neg, "net_density": pos - neg}


def pos_neg_ratio(text: str, pos_terms: Iterable[str], neg_terms: Iterable[str]) -> float:
    if not text:
        return 0.0
    tokens = tokenize_words(text)
    pos = count_token_hits(tokens, pos_terms)
    neg = count_token_hits(tokens, neg_terms)
    if pos == 0:
        return 0.0
    return pos / max(neg, 1)


def moving_average(values: List[float], window: int) -> List[float]:
    if window <= 0:
        raise ValueError("window must be positive")
    if not values:
        return []
    result: List[float] = []
    for idx in range(len(values)):
        start = max(0, idx - window + 1)
        segment = values[start : idx + 1]
        result.append(sum(segment) / len(segment))
    return result
