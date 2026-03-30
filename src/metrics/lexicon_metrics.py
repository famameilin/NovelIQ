from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence


def term_counts(text: str, terms: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not text:
        return counts
    for term in terms:
        if not term:
            continue
        count = text.count(term)
        if count:
            counts[term] = count
    return counts


def count_hits(text: str, terms: Iterable[str]) -> int:
    return sum(term_counts(text, terms).values())


def density(text: str, terms: Iterable[str]) -> float:
    total = count_hits(text, terms)
    return total / max(len(text), 1)


def count_token_hits(tokens: Sequence[str], terms: Iterable[str]) -> int:
    term_set = {term for term in terms if term}
    if not term_set:
        return 0
    return sum(1 for token in tokens if token in term_set)


def _is_phrase_term(term: str) -> bool:
    cleaned = term.strip()
    if not cleaned:
        return False
    if " " in cleaned:
        return True
    return len(cleaned) >= 2


def _count_non_overlapping_spans(text: str, terms: Iterable[str], tokens: Sequence[str]) -> dict[str, int]:
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
    if not terms:
        return {}

    text_value = text or ""
    return dict(_count_non_overlapping_spans(text_value, terms, tokens))


def count_mixed_hits(text: str, tokens: Sequence[str], terms: Iterable[str]) -> int:
    return sum(term_mixed_counts(text, tokens, terms).values())


def token_density(tokens: Sequence[str], terms: Iterable[str]) -> float:
    total = count_token_hits(tokens, terms)
    return total / max(len(tokens), 1)
