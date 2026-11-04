"""词表匹配核心函数"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from functools import lru_cache


def _is_phrase_term(term: str) -> bool:
    cleaned = term.strip()
    if not cleaned:
        return False
    if " " in cleaned:
        return True
    return len(cleaned) >= 2


class _PhraseMatcher:
    "一次扫描枚举全部短语候选，保留重叠词与同起点的短词"

    def __init__(self, terms: tuple[str, ...]) -> None:
        self.token_terms = frozenset(term.strip() for term in terms if term and term.strip())
        self.transitions: list[dict[str, int]] = [{}]
        self.failures = [0]
        self.outputs: list[list[str]] = [[]]
        for term in sorted(self.token_terms):
            if not _is_phrase_term(term):
                continue
            state = 0
            for char in term:
                target = self.transitions[state].get(char)
                if target is None:
                    target = len(self.transitions)
                    self.transitions[state][char] = target
                    self.transitions.append({})
                    self.failures.append(0)
                    self.outputs.append([])
                state = target
            self.outputs[state].append(term)
        pending = deque(self.transitions[0].values())
        while pending:
            state = pending.popleft()
            for char, target in self.transitions[state].items():
                fallback = self.failures[state]
                while fallback and char not in self.transitions[fallback]:
                    fallback = self.failures[fallback]
                self.failures[target] = self.transitions[fallback].get(char, 0)
                self.outputs[target].extend(self.outputs[self.failures[target]])
                pending.append(target)

    def spans(self, text: str) -> Iterable[tuple[int, int, str]]:
        "输出所有短语出现位置，筛选顺序由调用方决定"
        state = 0
        for index, char in enumerate(text):
            while state and char not in self.transitions[state]:
                state = self.failures[state]
            state = self.transitions[state].get(char, 0)
            for term in self.outputs[state]:
                yield index + 1 - len(term), index + 1, term


@lru_cache(maxsize=64)
def _phrase_matcher(terms: tuple[str, ...]) -> _PhraseMatcher:
    "按词表内容复用匹配器，词条变化时重新构建"
    return _PhraseMatcher(terms)


def _count_non_overlapping_spans(
    text: str, terms: Iterable[str], tokens: Sequence[str], *, phrase_spans: list[tuple[int, int, str]] | None = None
) -> dict[str, int]:
    """按长词优先策略统计非重叠匹配"""
    counts: dict[str, int] = defaultdict(int)
    if not text:
        return counts

    matcher = _phrase_matcher(tuple(terms))
    token_terms = matcher.token_terms
    candidates = list(matcher.spans(text)) if phrase_spans is None else phrase_spans

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

    occupied = bytearray(len(text))
    for start, end, term in candidates:
        if occupied.find(b"\x01", start, end) >= 0:
            continue
        occupied[start:end] = b"\x01" * (end - start)
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


class GroupedMixedMatcher:
    """共享短语扫描，各词表独立执行长词优先和非重叠筛选"""

    def __init__(self, groups: dict[str, list[str]]) -> None:
        self._groups = {category: tuple(terms) for category, terms in groups.items() if terms}
        self._categories: dict[str, list[str]] = defaultdict(list)
        for category, terms in self._groups.items():
            for term in _phrase_matcher(terms).token_terms:
                self._categories[term].append(category)
        self._matcher = _PhraseMatcher(tuple(self._categories))

    def count(self, text: str, tokens: Sequence[str]) -> dict[str, int]:
        phrase_spans: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
        for start, end, term in self._matcher.spans(text):
            for category in self._categories[term]:
                phrase_spans[category].append((start, end, term))

        candidate_tokens: dict[str, list[str]] = defaultdict(list)
        for token in tokens:
            cleaned = token.strip()
            for category in self._categories.get(cleaned, ()):
                candidate_tokens[category].append(cleaned)

        return {
            category: sum(
                _count_non_overlapping_spans(
                    text, terms, candidate_tokens[category], phrase_spans=phrase_spans[category],
                ).values()
            )
            for category, terms in self._groups.items()
        }


def get_emotion_spans(text: str, tokens: Sequence[str], terms: Iterable[str]) -> list[tuple[int, int, str]]:
    """获取情感词的非重叠位置，用于否定词检测"""
    if not text:
        return []

    spans: list[tuple[int, int, str]] = []
    term_values = tuple(terms)
    matcher = _phrase_matcher(term_values)
    counts = _count_non_overlapping_spans(text, term_values, tokens)
    matches_by_term: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for start, end, term in matcher.spans(text):
        matches_by_term[term].append((start, end))
    phrase_terms = sorted(matches_by_term, key=lambda term: (-len(term), term))
    token_terms = matcher.token_terms

    occupied: list[tuple[int, int]] = []

    for term in phrase_terms:
        for idx, end in matches_by_term[term]:
            if any(not (end <= occ_start or idx >= occ_end) for occ_start, occ_end in occupied):
                continue
            if counts.get(term, 0) > 0:
                spans.append((idx, end, term))
                occupied.append((idx, end))
                counts[term] -= 1

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
