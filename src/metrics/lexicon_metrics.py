"""词表匹配核心函数"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from src.utils.lexicon_parser import load_weighted_lexicon as _load_weighted_lexicon


def _is_phrase_term(term: str) -> bool:
    cleaned = term.strip()
    if not cleaned:
        return False
    if " " in cleaned:
        return True
    return len(cleaned) >= 2


def _count_non_overlapping_spans(text: str, terms: Iterable[str], tokens: Sequence[str]) -> dict[str, int]:
    """按长词优先策略统计非重叠匹配"""
    counts: dict[str, int] = defaultdict(int)
    if not text:
        return counts

    phrase_terms = sorted(
        {term.strip() for term in terms if term and _is_phrase_term(term.strip())},
        key=lambda term: (-len(term), term),
    )
    token_terms = {term.strip() for term in terms if term and term.strip()}

    candidates: list[tuple[int, int, str]] = []

    for term in phrase_terms:
        start = 0
        while True:
            idx = text.find(term, start)
            if idx < 0:
                break
            candidates.append((idx, idx + len(term), term))
            start = idx + 1

    cursor = 0
    for token in tokens:
        cleaned = token.strip() if token else ""
        if not cleaned or cleaned not in token_terms:
            continue

        start = text.find(cleaned, cursor)
        if start < 0:
            start = text.find(cleaned)
            if start < 0:
                continue
        end = start + len(cleaned)
        candidates.append((start, end, cleaned))
        cursor = end

    candidates.sort(key=lambda item: (-(item[1] - item[0]), item[0], item[2]))

    occupied: list[tuple[int, int]] = []
    for start, end, term in candidates:
        if any(not (end <= occ_start or start >= occ_end) for occ_start, occ_end in occupied):
            continue
        occupied.append((start, end))
        counts[term] += 1

    return counts


def term_mixed_counts(text: str, tokens: Sequence[str], terms: Iterable[str]) -> dict[str, int]:
    """返回词条级别的计数（phrase 模式）"""
    if not terms:
        return {}

    text_value = text or ""
    return dict(_count_non_overlapping_spans(text_value, terms, tokens))


def count_mixed_hits(text: str, tokens: Sequence[str], terms: Iterable[str]) -> int:
    """计算词表命中次数（phrase 模式）"""
    return sum(term_mixed_counts(text, tokens, terms).values())


def get_emotion_spans(text: str, tokens: Sequence[str], terms: Iterable[str]) -> list[tuple[int, int, str]]:
    """获取情感词的非重叠位置，用于否定词检测"""
    if not text:
        return []

    spans: list[tuple[int, int, str]] = []
    counts = _count_non_overlapping_spans(text, terms, tokens)

    phrase_terms = sorted(
        {term.strip() for term in terms if term and _is_phrase_term(term.strip())},
        key=lambda term: (-len(term), term),
    )
    token_terms = {term.strip() for term in terms if term and term.strip()}

    occupied: list[tuple[int, int]] = []

    for term in phrase_terms:
        start = 0
        while True:
            idx = text.find(term, start)
            if idx < 0:
                break
            end = idx + len(term)
            if any(not (end <= occ_start or idx >= occ_end) for occ_start, occ_end in occupied):
                start = idx + 1
                continue
            if counts.get(term, 0) > 0:
                spans.append((idx, end, term))
                occupied.append((idx, end))
                counts[term] -= 1
            start = idx + 1

    cursor = 0
    for token in tokens:
        cleaned = token.strip() if token else ""
        if not cleaned or cleaned not in token_terms:
            if token:
                cursor = text.find(token, cursor) + len(token) if text.find(token, cursor) >= 0 else cursor + len(token)
            continue

        start = text.find(cleaned, cursor)
        if start < 0:
            start = text.find(cleaned)
            if start < 0:
                continue
        end = start + len(cleaned)

        if any(not (end <= occ_start or start >= occ_end) for occ_start, occ_end in occupied):
            cursor = end
            continue

        if counts.get(cleaned, 0) > 0:
            spans.append((start, end, cleaned))
            occupied.append((start, end))
            counts[cleaned] -= 1
        cursor = end

    spans.sort(key=lambda x: x[0])
    return spans


def load_weighted_lexicon(filepath: str, default_weight: int = 1) -> dict[str, int]:
    """加载带权重词典"""
    return _load_weighted_lexicon(filepath, default_weight=default_weight)


def term_weighted_counts(
    text: str, tokens: Sequence[str], weighted_terms: Mapping[str, float]
) -> dict[str, tuple[int, float]]:
    """返回词条的命中次数和权重"""
    if not weighted_terms:
        return {}

    text_value = text or ""
    counts = _count_non_overlapping_spans(text_value, weighted_terms.keys(), tokens)

    result: dict[str, tuple[int, float]] = {}
    for term, count in counts.items():
        weight = weighted_terms.get(term, 1)
        result[term] = (count, weight)

    return result


def count_weighted_hits(text: str, tokens: Sequence[str], weighted_terms: Mapping[str, float]) -> float:
    """计算词条命中次数与权重的乘积和"""
    weighted_counts = term_weighted_counts(text, tokens, weighted_terms)
    return sum(count * weight for count, weight in weighted_counts.values())
