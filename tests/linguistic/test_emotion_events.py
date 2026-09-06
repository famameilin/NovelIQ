"""LTP sdp 情绪事件与 mNEG 修正测试（2026-09-05 B 批，纯函数，不加载模型）"""

from __future__ import annotations

from src.linguistic import analyze_paragraph
from src.linguistic.emotion_events import extract_emotion_events, mneg_corrected_counts
from src.linguistic.ltp_client import LtpPipelineOutput
from src.linguistic.schema import LtpSdpArc, LtpToken

#: 测试用极性词表（词典只做极性候选标记）
POS_TERMS = {"高兴": 1.0, "喜欢": 1.0}
NEG_TERMS = {"生气": 1.0, "害怕": 1.0}


def _result_for(words: list[str], sdp: list[dict[str, list]] | None = None):
    """词元与原文逐字对齐的 LTP 输出（sdp 由用例给定，坐标为句内 1 起索引）"""
    text = "".join(words)
    heads = [0] + [1] * (len(words) - 1) if len(words) > 1 else [0]
    labels = ["HED"] + ["ATT"] * (len(words) - 1)
    return analyze_paragraph(
        text,
        LtpPipelineOutput(
            cws=[words],
            pos=[["v"] * len(words)],
            ner=[[]],
            dep=[{"head": heads, "label": labels}],
            sdp=sdp or [],
        ),
    )


class TestExtractEmotionEvents:
    def test_predicate_with_holder_from_agt(self) -> None:
        # 生气(head=1) ←AGT─ 贺伯安(2)
        words = ["生气", "贺伯安"]
        sdp = [{"head": [1, 1], "dependent": [2, 0], "label": ["AGT", "ROOT"]}]
        events = extract_emotion_events(_result_for(words, sdp), POS_TERMS, NEG_TERMS)
        assert len(events) == 1
        event = events[0]
        assert event.predicate == "生气"
        assert event.polarity == "negative"
        assert event.holder == "贺伯安"
        assert event.target is None
        assert event.negated is False
        assert event.local_start_char == 0 and event.local_end_char == 2

    def test_target_from_datv_and_degree_from_mdepd(self) -> None:
        # 害怕(1) ←DATV─ 安危(2)、←mDEPD─ 很(3)
        words = ["害怕", "安危", "很"]
        sdp = [{"head": [1, 1, 1], "dependent": [2, 0, 3], "label": ["DATV", "ROOT", "mDEPD"]}]
        events = extract_emotion_events(_result_for(words, sdp), POS_TERMS, NEG_TERMS)
        assert len(events) == 1
        event = events[0]
        assert event.predicate == "害怕"
        assert event.target == "安危"
        assert event.degree_words == ("很",)

    def test_negation_flag_from_mneg(self) -> None:
        # 喜欢(1) ←mNEG─ 不(2)
        words = ["喜欢", "不"]
        sdp = [{"head": [1, 1], "dependent": [2, 0], "label": ["mNEG", "ROOT"]}]
        events = extract_emotion_events(_result_for(words, sdp), POS_TERMS, NEG_TERMS)
        assert len(events) == 1
        assert events[0].negated is True

    def test_non_lexicon_tokens_produce_no_events(self) -> None:
        result = _result_for(["刀光", "剑影"])
        assert extract_emotion_events(result, POS_TERMS, NEG_TERMS) == []


class TestMnegCorrectedCounts:
    def test_flip_only_when_head_of_mneg(self) -> None:
        # 词元：高兴(1) 喜欢(2)；喜欢是 mNEG head → 翻转为负，高兴保持正
        text = "高兴喜欢"
        result = _result_for(["高兴", "喜欢"])
        arcs = [LtpSdpArc(head_index=2, dependent_index=1, label="mNEG")]
        pos, neg = mneg_corrected_counts(text, result.tokens, arcs, POS_TERMS, NEG_TERMS)
        assert (pos, neg) == (1.0, 1.0)

    def test_no_negation_keeps_lexicon_polarity(self) -> None:
        result = _result_for(["高兴"])
        pos, neg = mneg_corrected_counts("高兴", result.tokens, [], POS_TERMS, NEG_TERMS)
        assert (pos, neg) == (1.0, 0.0)

    def test_negated_negative_word_flips_positive(self) -> None:
        # 别(1) ←mNEG─ 害怕(2)：负词翻转为正（否定词是真实词元，与 LTP 输出一致）
        result = _result_for(["别", "害怕"])
        arcs = [LtpSdpArc(head_index=2, dependent_index=1, label="mNEG")]
        pos, neg = mneg_corrected_counts("别害怕", result.tokens, arcs, POS_TERMS, NEG_TERMS)
        assert (pos, neg) == (1.0, 0.0)

    def test_empty_text_returns_zero(self) -> None:
        assert mneg_corrected_counts("", [], [], POS_TERMS, NEG_TERMS) == (0.0, 0.0)

    def test_missing_head_token_does_not_flip(self) -> None:
        """mNEG head 指向不存在的词元时不翻转（防御，不冒充否定覆盖）"""
        token = LtpToken(
            token_index=1, text="高兴", local_start_char=0, local_end_char=2, pos_tag="a", pos_group="adj"
        )
        arcs = [LtpSdpArc(head_index=9, dependent_index=2, label="mNEG")]
        pos, neg = mneg_corrected_counts("高兴", [token], arcs, POS_TERMS, NEG_TERMS)
        assert (pos, neg) == (1.0, 0.0)
