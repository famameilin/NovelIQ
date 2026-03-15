from __future__ import annotations

from typing import Dict, Iterable, Sequence


def term_counts(text: str, terms: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
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


def token_density(tokens: Sequence[str], terms: Iterable[str]) -> float:
    total = count_token_hits(tokens, terms)
    return total / max(len(tokens), 1)
