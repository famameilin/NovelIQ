from __future__ import annotations

from collections import Counter, defaultdict
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

def _phrase_span_counts(text: str, terms: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    if not text:
        return counts

    phrase_terms = sorted(
        {term.strip() for term in terms if term and _is_phrase_term(term.strip())},
        key=lambda term: (-len(term), term),
    )
    if not phrase_terms:
        return counts

    index = 0
    text_len = len(text)
    while index < text_len:
        matched_term = next((term for term in phrase_terms if text.startswith(term, index)), None)
        if matched_term is None:
            index += 1
            continue

        counts[matched_term] += 1
        index += len(matched_term)

    return counts

def term_mixed_counts(text: str, tokens: Sequence[str], terms: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    if not terms:
        return counts

    text_value = text or ""
    token_counter = _token_counts(tokens)
    phrase_counts = _phrase_span_counts(text_value, terms)

    for term in terms:
        cleaned = term.strip() if term else ""
        if not cleaned:
            continue

        token_hit = token_counter.get(cleaned, 0)
        phrase_hit = phrase_counts.get(cleaned, 0)
        mixed_hit = max(token_hit, phrase_hit)
        if mixed_hit > 0:
            counts[cleaned] = mixed_hit

    return counts

def count_mixed_hits(text: str, tokens: Sequence[str], terms: Iterable[str]) -> int:
    return sum(term_mixed_counts(text, tokens, terms).values())

def token_density(tokens: Sequence[str], terms: Iterable[str]) -> float:
    total = count_token_hits(tokens, terms)
    return total / max(len(tokens), 1)
