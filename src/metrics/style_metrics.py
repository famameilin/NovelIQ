from __future__ import annotations

from collections.abc import Sequence

from src.config import settings
from src.text_processing.text_utils import dialogue_length


def ttr(tokens: Sequence[str]) -> float:
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


def mtld(tokens: Sequence[str], threshold: float | None = None) -> float | None:
    if threshold is None:
        threshold = settings.metrics.mtld_threshold
    if not tokens:
        return 0.0

    types: set[str] = set()
    factors = 0.0
    token_count = 0

    for token in tokens:
        token_count += 1
        types.add(token)
        current_ttr = len(types) / token_count
        if current_ttr <= threshold:
            factors += 1.0
            types = set()
            token_count = 0

    if token_count > 0:
        remainder_ttr = len(types) / token_count
        if remainder_ttr != 1.0:
            factors += (1.0 - remainder_ttr) / (1.0 - threshold)

    if factors == 0:
        # 全唯一词（或 TTR 从未跌破阈值）时 MTLD 数学上无定义，返回 None
        # （§19.12 修复：不再退化为 len(tokens)）
        return None
    return len(tokens) / factors


def dialogue_ratio(text: str) -> float:
    if not text:
        return 0.0
    return dialogue_length(text) / len(text)
