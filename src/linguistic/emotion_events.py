"""LTP sdp 情绪事件抽取（2026-09-05 B 批：与词典情绪对应的模型线）

口径（用户定稿）：
- 情绪词典只承担谓词极性候选标记（该词是正面还是负面情绪词），不再做任何
  结构判定；持有者（AGT）/对象（DATV）/否定（mNEG）/程度（mDEPD）全部来自
  LTP sdp 的模型判定。
- mNEG 接管词典否定翻转：情绪词命中是否翻转由 sdp 的 mNEG 弧（模型习得的
  否定辖域）决定，替代 negation.py 的窗口规则（仅在本模块的修正口径内；
  paragraph_metrics 原值由 linguistic 阶段回写，见 workflows/linguistic.py）。
- EXP 不作为持有者来源：实测心理谓词的持有者被 LTP 标为 AGT，EXP 不可靠。

纯函数，不依赖模型实例；测试可直接构造 ParagraphLinguisticResult。
"""

from __future__ import annotations

from collections.abc import Mapping

from src.metrics.lexicon_metrics import get_emotion_spans

from .schema import EmotionEvent, LtpSdpArc, LtpToken, ParagraphLinguisticResult

#: sdp 语义角色标签（首手实测标定，见 docs 09-05 方案）
_SDP_HOLDER_LABEL = "AGT"
_SDP_TARGET_LABEL = "DATV"
_SDP_NEGATION_LABEL = "mNEG"
_SDP_DEGREE_LABEL = "mDEPD"


def _group_sdp_arcs(
    sdp_arcs: list[LtpSdpArc],
    tokens_by_index: Mapping[int, LtpToken],
) -> tuple[dict[int, str], dict[int, str], set[int], dict[int, list[str]]]:
    """按 head 谓词聚合 sdp 论元：持有者/对象/否定谓词集合/程度词"""
    holders: dict[int, str] = {}
    targets: dict[int, str] = {}
    negated_heads: set[int] = set()
    degrees: dict[int, list[str]] = {}
    for arc in sdp_arcs:
        dependent = tokens_by_index.get(arc.dependent_index)
        if dependent is None:
            continue
        if arc.label == _SDP_HOLDER_LABEL:
            holders.setdefault(arc.head_index, dependent.text)
        elif arc.label == _SDP_TARGET_LABEL:
            targets.setdefault(arc.head_index, dependent.text)
        elif arc.label == _SDP_NEGATION_LABEL:
            negated_heads.add(arc.head_index)
        elif arc.label == _SDP_DEGREE_LABEL:
            degrees.setdefault(arc.head_index, []).append(dependent.text)
    return holders, targets, negated_heads, degrees


def _polarity_of(token_text: str, pos_terms: Mapping[str, float], neg_terms: Mapping[str, float]) -> str | None:
    if token_text in pos_terms:
        return "positive"
    if token_text in neg_terms:
        return "negative"
    return None


def extract_emotion_events(
    result: ParagraphLinguisticResult,
    pos_terms: Mapping[str, float],
    neg_terms: Mapping[str, float],
) -> list[EmotionEvent]:
    """从段落语言结果抽取情绪事件（词典极性标记 × sdp 结构）

    事件 = 词典命中的情绪谓词词元；持有者/对象取该谓词在 sdp 上的
    AGT/DATV 依存词，否定/程度取 mNEG/mDEPD 依存词。
    """
    tokens_by_index = {token.token_index: token for token in result.tokens}
    holders, targets, negated_heads, degrees = _group_sdp_arcs(result.sdp_arcs, tokens_by_index)

    events: list[EmotionEvent] = []
    for token in result.tokens:
        polarity = _polarity_of(token.text, pos_terms, neg_terms)
        if polarity is None:
            continue
        events.append(
            EmotionEvent(
                predicate=token.text,
                predicate_token_index=token.token_index,
                polarity=polarity,
                holder=holders.get(token.token_index),
                target=targets.get(token.token_index),
                negated=token.token_index in negated_heads,
                degree_words=tuple(degrees.get(token.token_index, ())),
                local_start_char=token.local_start_char,
                local_end_char=token.local_end_char,
            )
        )
    return events


def _span_is_negated(
    span_start: int,
    tokens: list[LtpToken],
    negated_heads: set[int],
) -> bool:
    """情绪词 span 是否处于 mNEG 辖域：span 起点所在词元（或首个重叠词元）
    是 mNEG 弧的 head 即翻转；找不到承载词元时按未否定处理"""
    for token in tokens:
        if token.local_start_char <= span_start < token.local_end_char:
            return token.token_index in negated_heads
    for token in tokens:
        if token.local_start_char < span_start and span_start < token.local_end_char:
            return token.token_index in negated_heads
    return False


def mneg_corrected_counts(
    text: str,
    tokens: list[LtpToken],
    sdp_arcs: list[LtpSdpArc],
    pos_terms: Mapping[str, float],
    neg_terms: Mapping[str, float],
) -> tuple[float, float]:
    """mNEG 接管否定翻转的词典情绪计数（修正口径）

    命中集与 paragraph_metrics 完全一致（同一 get_emotion_spans 短语匹配），
    唯一差异是翻转判定：sdp mNEG（模型习得辖域）替代 negation.py 窗口规则。
    Returns:
        (修正后的正面命中数, 修正后的负面命中数)
    """
    if not text:
        return 0.0, 0.0
    token_texts = [token.text for token in tokens if token.text]
    pos_spans = get_emotion_spans(text, token_texts, pos_terms.keys())
    neg_spans = get_emotion_spans(text, token_texts, neg_terms.keys())
    if not pos_spans and not neg_spans:
        return 0.0, 0.0

    tokens_by_index = {token.token_index: token for token in tokens if token.text}
    _holders, _targets, negated_heads, _degrees = _group_sdp_arcs(sdp_arcs, tokens_by_index)
    ordered_tokens = [token for token in tokens if token.text]

    pos_count = 0.0
    neg_count = 0.0
    for start, _end, _term in pos_spans:
        if _span_is_negated(start, ordered_tokens, negated_heads):
            neg_count += 1.0
        else:
            pos_count += 1.0
    for start, _end, _term in neg_spans:
        if _span_is_negated(start, ordered_tokens, negated_heads):
            pos_count += 1.0
        else:
            neg_count += 1.0
    return pos_count, neg_count


__all__ = [
    "EmotionEvent",
    "extract_emotion_events",
    "mneg_corrected_counts",
]
