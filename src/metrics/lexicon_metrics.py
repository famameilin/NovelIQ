from __future__ import annotations

from collections import Counter
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


def _token_counts(tokens: Sequence[str]) -> Counter[str]:
    return Counter(token for token in tokens if token)


def _is_phrase_term(term: str) -> bool:
    cleaned = term.strip()
    if not cleaned:
        return False
    if " " in cleaned:
        return True
    return len(cleaned) >= 2


def term_mixed_counts(text: str, tokens: Sequence[str], terms: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    if not terms:
        return counts

    text_value = text or ""
    token_counter = _token_counts(tokens)

    for term in terms:
        cleaned = term.strip() if term else ""
        if not cleaned:
            continue

        token_hit = token_counter.get(cleaned, 0)
        phrase_hit = text_value.count(cleaned) if text_value and _is_phrase_term(cleaned) else 0
        mixed_hit = max(token_hit, phrase_hit)
        if mixed_hit > 0:
            counts[cleaned] = mixed_hit

    return counts


def count_mixed_hits(text: str, tokens: Sequence[str], terms: Iterable[str]) -> int:
    return sum(term_mixed_counts(text, tokens, terms).values())


def token_density(tokens: Sequence[str], terms: Iterable[str]) -> float:
    total = count_token_hits(tokens, terms)
    return total / max(len(tokens), 1)
