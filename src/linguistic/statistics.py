"""正式语言阶段的逐段统计与情绪观测计算"""

from __future__ import annotations

from typing import Any

from src.lexicons.tables import NEGATIVE_TERMS, POSITIVE_TERMS
from src.linguistic.emotion_events import extract_emotion_events, mneg_corrected_counts
from src.linguistic.schema import ParagraphLinguisticResult
from src.metrics.lexicon_metrics import get_emotion_spans
from src.metrics.negation import is_flipped, load_negation_spec


def _window_rule_counts(text: str, token_texts: list[str]) -> tuple[float, float]:
    """按窗口否定规则计算与 LTP 词元对应的词典情绪基线"""
    negation_spec = load_negation_spec()
    pos_count = neg_count = 0.0
    for terms, positive in ((POSITIVE_TERMS, True), (NEGATIVE_TERMS, False)):
        for start, _end, _term in get_emotion_spans(text, token_texts, terms.keys()):
            if positive != is_flipped(text, start, negation_spec):
                pos_count += 1.0
            else:
                neg_count += 1.0
    return pos_count, neg_count


def build_paragraph_statistics(text: str, result: ParagraphLinguisticResult) -> dict[str, Any]:
    """由正式 LTP 输出生成可持久化的逐段统计与情绪词元引用"""
    for token in result.tokens:
        if (
            not 0 <= token.local_start_char < token.local_end_char <= len(text)
            or text[token.local_start_char:token.local_end_char] != token.text
        ):
            raise ValueError("语言词元必须与原文区间一致")
    data = result.to_dict()
    events = extract_emotion_events(result, POSITIVE_TERMS, NEGATIVE_TERMS)
    tokens_by_index = {token.token_index: token for token in result.tokens}
    holders: dict[int, int] = {}
    for arc in result.sdp_arcs:
        if arc.label == "AGT" and arc.dependent_index in tokens_by_index:
            holders.setdefault(arc.head_index, arc.dependent_index)
    data["emotion_events"] = [
        {**event.to_dict(), "holder_token_index": holders.get(event.predicate_token_index)} for event in events
    ]
    data["mneg_pos_count"], data["mneg_neg_count"] = mneg_corrected_counts(
        text, result.tokens, result.sdp_arcs, POSITIVE_TERMS, NEGATIVE_TERMS
    )
    data["lexicon_pos_count"], data["lexicon_neg_count"] = _window_rule_counts(
        text, [token.text for token in result.tokens]
    )
    data["word_length_counts"] = {
        key: result.word_length_counts.get(key, 0) for key in ("1", "2", "3", "4", "5_plus")
    }
    return data
