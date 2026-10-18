"从正式语言事实计算领域投影，算法与模型规则由本领域维护"

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from src.lexicons.tables import NEGATIVE_TERMS, POSITIVE_TERMS
from src.linguistic.emotion_events import extract_emotion_events, mneg_corrected_counts
from src.linguistic.ltp_client import _count_dependency_statistics
from src.linguistic.schema import LtpDependencyArc, LtpSdpArc, LtpToken, ParagraphLinguisticResult
from src.metrics.negation import is_flipped, load_negation_spec

_DEP_PREFIX = "dep:"
_SDP_PREFIX = "sdp:"
_SENTENCE_CODE_TO_KEY = {
    "sentence_short": "short",
    "sentence_medium": "medium",
    "sentence_long": "long",
    "sentence_compound": "compound",
    "sentence_parallel_candidate": "parallel_candidate",
}
_DEFAULT_POS_GROUP = "other"


def _pos_group_of(raw_pos: object) -> str:
    "POS 归一分组投影（版本化代码合同；未映射标签归 other）"
    from src.linguistic.ltp_client import POS_GROUP_MAP

    if raw_pos is None:
        return _DEFAULT_POS_GROUP
    return POS_GROUP_MAP.get(str(raw_pos), _DEFAULT_POS_GROUP)


def _normalized_entity_type(raw_entity_type: object) -> str | None:
    "NER 归一类型投影（版本化代码合同；未映射类型为 NULL）"
    from src.linguistic.ltp_client import ENTITY_TYPE_MAP

    if raw_entity_type is None:
        return None
    return ENTITY_TYPE_MAP.get(str(raw_entity_type))


def _window_rule_counts(
    text: str,
    token_texts: list[str],
    pos_terms: Mapping[str, float],
    neg_terms: Mapping[str, float],
    is_flipped: Any,
    negation_spec: Any,
) -> tuple[float, float]:
    "窗口规则（negation.is_flipped）词典情绪计数：与 metrics 阶段同算法"
    from src.metrics.lexicon_metrics import get_emotion_spans

    if not text:
        return (0.0, 0.0)
    pos_spans = get_emotion_spans(text, token_texts, pos_terms.keys())
    neg_spans = get_emotion_spans(text, token_texts, neg_terms.keys())
    pos_count = 0.0
    neg_count = 0.0
    for start, _end, _term in pos_spans:
        if is_flipped(text, start, negation_spec):
            neg_count += 1.0
        else:
            pos_count += 1.0
    for start, _end, _term in neg_spans:
        if is_flipped(text, start, negation_spec):
            pos_count += 1.0
        else:
            neg_count += 1.0
    return (pos_count, neg_count)


def project_linguistic_features(sources: dict[str, Any]) -> list[SimpleNamespace]:
    if not sources:
        return []
    metric_rows = sources["metric_rows"]
    paragraph_texts = sources["paragraph_texts"]
    tokens_by_paragraph = sources["tokens_by_paragraph"]
    arcs_by_paragraph = sources["arcs_by_paragraph"]
    token_index_by_span = sources["token_index_by_span"]
    patterns_by_paragraph = sources["patterns_by_paragraph"]
    negation_spec = load_negation_spec()
    results: list[SimpleNamespace] = []
    for metric in metric_rows:
        paragraph_id = int(metric["paragraph_id"])
        text_of_paragraph = paragraph_texts.get(paragraph_id) or ""
        tokens: list[LtpToken] = []
        for row in tokens_by_paragraph.get(paragraph_id, []):
            start_char = int(row.start_char)
            end_char = int(row.end_char)
            ltp_index = int(row.token_index) + 1
            tokens.append(
                LtpToken(
                    token_index=ltp_index,
                    text=text_of_paragraph[start_char:end_char],
                    local_start_char=start_char,
                    local_end_char=end_char,
                    pos_tag=str(row.raw_pos or "o"),
                    pos_group=_pos_group_of(row.raw_pos),
                )
            )
        dependency_arcs: list[LtpDependencyArc] = []
        sdp_arcs: list[LtpSdpArc] = []
        for row in arcs_by_paragraph.get(paragraph_id, []):
            code = str(row.relation_code)
            head_ltp_index = 0 if row.head_span_id is None else token_index_by_span.get(str(row.head_span_id), -1) + 1
            dependent_ltp_index = int(row.dependent_index) + 1
            if code.startswith(_DEP_PREFIX):
                dependency_arcs.append(
                    LtpDependencyArc(
                        dependent_index=dependent_ltp_index,
                        head_index=head_ltp_index,
                        relation=code[len(_DEP_PREFIX) :],
                    )
                )
            elif code.startswith(_SDP_PREFIX):
                sdp_arcs.append(
                    LtpSdpArc(
                        head_index=head_ltp_index, dependent_index=dependent_ltp_index, label=code[len(_SDP_PREFIX) :]
                    )
                )
        word_length_counts: dict[str, int] = {"1": 0, "2": 0, "3": 0, "4": 0, "5_plus": 0}
        pos_counts: dict[str, int] = {}
        for token in tokens:
            length = token.local_end_char - token.local_start_char
            bucket = "5_plus" if length >= 5 else str(length)
            word_length_counts[bucket] = word_length_counts.get(bucket, 0) + 1
            pos_counts[token.pos_group] = pos_counts.get(token.pos_group, 0) + 1
        node_count, root_count, depth_sum, depth_max, relation_counts = _count_dependency_statistics(dependency_arcs)
        pattern_counts = {
            _SENTENCE_CODE_TO_KEY[code]: count for code, count in patterns_by_paragraph.get(paragraph_id, {}).items()
        }
        result = ParagraphLinguisticResult(
            ltp_token_count=len(tokens),
            tokens=tokens,
            word_length_counts=word_length_counts,
            pos_counts=pos_counts,
            sentence_count=int(metric["sentence_count"] or 0),
            sentence_pattern_counts=pattern_counts,
            dependency_arcs=dependency_arcs,
            dependency_node_count=node_count,
            dependency_root_count=root_count,
            dependency_depth_sum=depth_sum,
            dependency_depth_max=depth_max,
            dependency_relation_counts=relation_counts,
            sdp_arcs=sdp_arcs,
        )
        events = extract_emotion_events(result, POSITIVE_TERMS, NEGATIVE_TERMS)
        mneg_pos, mneg_neg = mneg_corrected_counts(
            text_of_paragraph, result.tokens, result.sdp_arcs, POSITIVE_TERMS, NEGATIVE_TERMS
        )
        lexicon_pos, lexicon_neg = _window_rule_counts(
            text_of_paragraph,
            [token.text for token in tokens],
            POSITIVE_TERMS,
            NEGATIVE_TERMS,
            is_flipped,
            negation_spec,
        )
        results.append(
            SimpleNamespace(
                paragraph_id=paragraph_id,
                chapter_id=None,
                ltp_token_count=len(tokens),
                word_length_counts=word_length_counts,
                pos_counts=pos_counts,
                sentence_count=int(metric["sentence_count"] or 0),
                sentence_pattern_counts=pattern_counts,
                dependency_node_count=node_count,
                dependency_root_count=root_count,
                dependency_depth_sum=depth_sum,
                dependency_depth_max=depth_max,
                dependency_relation_counts=relation_counts,
                emotion_event_count=len(events),
                emotion_pos_event_count=sum(1 for event in events if event.polarity == "positive"),
                emotion_neg_event_count=sum(1 for event in events if event.polarity == "negative"),
                emotion_events=[event.to_dict() for event in events],
                lexicon_pos_count=lexicon_pos,
                lexicon_neg_count=lexicon_neg,
                mneg_pos_count=mneg_pos,
                mneg_neg_count=mneg_neg,
                boundary_pos_score_sum=float(metric["boundary_pos_score_sum"])
                if metric["boundary_pos_score_sum"] is not None
                else None,
                boundary_neg_score_sum=float(metric["boundary_neg_score_sum"])
                if metric["boundary_neg_score_sum"] is not None
                else None,
            )
        )
    return results
