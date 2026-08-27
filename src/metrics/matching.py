"""增强匹配（Enhanced Matching v2）：phrase=子串+token（默认）、fuzzy=phrase+编辑距离容错。
复用 lexicon_metrics._count_non_overlapping_spans，处理未登录词/分词变体。"""

from __future__ import annotations

from collections.abc import Sequence


def count_token_hits_enhanced(
    text: str,
    tokens: Sequence[str],
    terms: Sequence[str],
    mode: str = "phrase",
) -> int:
    """多模式命中计数：phrase=子串+token（默认，处理未登录词），fuzzy=phrase+编辑距离容错。"""
    if not tokens or not terms:
        return 0

    term_set = {t for t in terms if t}
    if not term_set:
        return 0

    if mode == "phrase":
        return _count_phrase_hits(text, tokens, term_set)

    if mode == "fuzzy":
        return _count_fuzzy_hits(text, tokens, term_set)

    raise ValueError(f"Unknown match mode: {mode}, expected 'phrase' or 'fuzzy'")


def _count_phrase_hits(text: str, tokens: Sequence[str], term_set: set[str]) -> int:
    """短语匹配：子串+token，长词优先、非重叠span、单字不参与子串。"""
    from .lexicon_metrics import _count_non_overlapping_spans

    counts = _count_non_overlapping_spans(text, term_set, tokens)
    return sum(counts.values())


def _count_fuzzy_hits(text: str, tokens: Sequence[str], term_set: set[str], max_edit_distance: int = 1) -> int:
    """模糊匹配：phrase+编辑距离≤1（仅长度≥2，慢3-5x，限tension等关键路径）。"""
    base_count = _count_phrase_hits(text, tokens, term_set)

    fuzzy_hits = 0
    matched_tokens = set()

    for token in tokens:
        if not token or len(token) < 2 or token in term_set or token in matched_tokens:
            continue

        for term in term_set:
            if len(term) < 2:
                continue
            if _edit_distance(token, term) <= max_edit_distance:
                fuzzy_hits += 1
                matched_tokens.add(token)
                break

    return base_count + fuzzy_hits


def _edit_distance(s1: str, s2: str) -> int:
    """Levenshtein编辑距离，空间优化DP O(min(m,n))。"""
    if len(s1) < len(s2):
        return _edit_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))

    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (0 if c1 == c2 else 1)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]
