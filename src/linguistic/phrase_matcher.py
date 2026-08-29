"""固定短语匹配器（《分析能力扩展路线图》§B2 / §5.5）

- 词表命中：词典按词条长度降序做最长匹配优先，同起点或交叠命中按
  贪心非重叠消解，全部命中行保留用于审计
- 四字候选：连续 4 个汉字且未落在任何词表命中区间内的片段，仅候选
  不伪造词表来源
- is_metric_hit：词表命中行是否计入正式固定短语密度由调用方决定；
  四字候选行恒为 False（候选不伪造词表来源）
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 连续汉字片段（四字候选判定）
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{4,}")
_LONGEST_MATCH_FLOOR = 2  # 单字不参与短语命中


@dataclass(frozen=True)
class PhraseMatch:
    """段落内一个短语命中或四字候选"""

    surface_text: str
    phrase_type: str | None
    local_start_char: int
    local_end_char: int
    match_kind: str
    lexicon_key: str | None
    lexicon_version_hash: str | None
    is_metric_hit: bool


def _lexicon_hits(text: str, term_by_length: dict[int, list[str]]) -> list[tuple[str, int, int]]:
    """最长匹配优先 + 非重叠贪心：返回 (surface, start, end)。"""
    hits: list[tuple[str, int, int]] = []
    occupied: list[tuple[int, int]] = []
    for length in sorted(term_by_length, reverse=True):
        for term in term_by_length[length]:
            start = 0
            while True:
                found = text.find(term, start)
                if found < 0:
                    break
                end = found + length
                if not any(o_start < end and o_end > found for o_start, o_end in occupied):
                    hits.append((term, found, end))
                    occupied.append((found, end))
                start = found + 1
    hits.sort(key=lambda h: h[1])
    return hits


def _four_char_candidates(text: str, hit_spans: list[tuple[int, int]]) -> list[tuple[str, int, int]]:
    """未落命中区间的连续四字及以上汉字片段，按最长优先切出四字候选。"""
    candidates: list[tuple[str, int, int]] = []
    for match in _CJK_RUN_RE.finditer(text):
        run_start = match.start()
        run_end = match.end()
        cursor = run_start
        while cursor + 4 <= run_end:
            if any(o_start < cursor + 4 and o_end > cursor for o_start, o_end in hit_spans):
                cursor += 1
                continue
            candidates.append((text[cursor : cursor + 4], cursor, cursor + 4))
            cursor += 4
    return candidates


def match_fixed_phrases(
    text: str,
    lexicon_terms: list[str],
    *,
    lexicon_key: str,
    lexicon_version_hash: str,
    metric_enabled: bool = False,
    phrase_type: str | None = None,
    four_char_candidate_enabled: bool = True,
) -> list[PhraseMatch]:
    """匹配一段文本的固定短语命中与四字候选（§5.5 行语义）"""
    if not lexicon_terms or not text:
        return []

    term_by_length: dict[int, list[str]] = {}
    for term in lexicon_terms:
        term = term.strip()
        if len(term) >= _LONGEST_MATCH_FLOOR:
            term_by_length.setdefault(len(term), []).append(term)

    lexicon_hits = _lexicon_hits(text, term_by_length)
    hit_spans = [(start, end) for _, start, end in lexicon_hits]

    results = [
        PhraseMatch(
            surface_text=surface,
            phrase_type=phrase_type,
            local_start_char=start,
            local_end_char=end,
            match_kind="lexicon",
            lexicon_key=lexicon_key,
            lexicon_version_hash=lexicon_version_hash,
            is_metric_hit=metric_enabled,
        )
        for surface, start, end in lexicon_hits
    ]

    if four_char_candidate_enabled:
        for surface, start, end in _four_char_candidates(text, hit_spans):
            results.append(
                PhraseMatch(
                    surface_text=surface,
                    phrase_type=None,
                    local_start_char=start,
                    local_end_char=end,
                    match_kind="four_char_candidate",
                    lexicon_key=None,
                    lexicon_version_hash=None,
                    is_metric_hit=False,
                )
            )

    results.sort(key=lambda m: (m.local_start_char, m.local_end_char))
    return results