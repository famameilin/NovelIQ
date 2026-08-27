"""段落级原始计数与充分统计量（§5.3，分子/分母口径不算密度）。
对应 ParagraphMetricRow（缺 paragraph_id/surface_tension）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.metrics.lexicon_metrics import count_mixed_hits, get_emotion_spans
from src.metrics.matching import count_token_hits_enhanced
from src.metrics.negation import is_flipped, load_negation_spec
from src.utils.text_utils import dialogue_length, split_sentences

# 与 style_metrics.metaphor_density 的 markers 保持一致
# （该处未导出常量，此处本地声明一份，避免反向依赖）
METAPHOR_MARKERS = ("像", "如", "仿佛", "宛若", "犹如", "好似")

_PAUSE_PATTERN = re.compile(r"[，、；,;]")


@dataclass(frozen=True)
class ParagraphMetricCounts:
    """段落级原始计数与充分统计量（§5.3，全部为分子/分母口径，非密度）"""

    token_count: int
    char_count: int
    sentence_count: int
    sentence_char_sum: float
    sentence_char_sum_sq: float
    positive_weight_sum: float
    negative_weight_sum: float
    fight_weight_sum: float
    exclaim_count: int
    question_count: int
    pause_count: int
    dialogue_char_count: int
    sensory_hit_count: int
    imagery_hit_count: int
    metaphor_sentence_count: int
    function_word_counts: dict[str, int]
    semantic_category_counts: dict[str, int]


def compute_paragraph_metric_counts(
    text: str,
    tokens: list[str],
    lexicons: dict[str, Any],
) -> ParagraphMetricCounts:
    """段落级原始计数与充分统计量（分子/分母口径，2026-08-16 M3/M4：权重弃用统一1.0计命中数）。
    lexicons缺失按空处理；情绪计数经negation共享层翻转，空文本/空词表不触发表读取。"""
    token_count = len(tokens)
    char_count = len(text)

    sentences = split_sentences(text)
    sentence_count = len(sentences)
    sentence_char_sum = float(sum(len(sentence) for sentence in sentences))
    sentence_char_sum_sq = float(sum(len(sentence) ** 2 for sentence in sentences))

    pos_terms = lexicons.get("pos_terms") or {}
    neg_terms = lexicons.get("neg_terms") or {}
    positive_weight_sum = 0.0
    negative_weight_sum = 0.0

    pos_spans = get_emotion_spans(text, tokens, pos_terms.keys())
    neg_spans = get_emotion_spans(text, tokens, neg_terms.keys())
    if pos_spans or neg_spans:
        # 2026-08-16 M5：否定判定改走共享层 negation.is_flipped
        # （句边界 + longest-match 去重 + token 级距离约束 + hard/modal/double 分类）
        spec = load_negation_spec()
        for start, _end, _term in pos_spans:
            if is_flipped(text, start, spec):
                negative_weight_sum += 1.0
            else:
                positive_weight_sum += 1.0
        for start, _end, _term in neg_spans:
            if is_flipped(text, start, spec):
                positive_weight_sum += 1.0
            else:
                negative_weight_sum += 1.0

    fight_terms = lexicons.get("fight_terms") or {}
    fight_weight_sum = float(count_token_hits_enhanced(text, tokens, list(fight_terms.keys()), mode="fuzzy"))

    exclaim_count = text.count("!") + text.count("！")
    question_count = text.count("?") + text.count("？")
    pause_count = len(_PAUSE_PATTERN.findall(text))

    dialogue_char_count = dialogue_length(text)

    sensory = lexicons.get("sensory") or []
    imagery = lexicons.get("imagery") or []
    sensory_hit_count = count_mixed_hits(text, tokens, sensory)
    imagery_hit_count = count_mixed_hits(text, tokens, imagery)

    metaphor_sentence_count = sum(1 for sentence in sentences if any(marker in sentence for marker in METAPHOR_MARKERS))

    function_words = lexicons.get("function_words") or []
    function_word_set = {word for word in function_words if word}
    function_word_counts: dict[str, int] = {}
    for token in tokens:
        if token in function_word_set:
            function_word_counts[token] = function_word_counts.get(token, 0) + 1

    semantic_categories = lexicons.get("semantic_categories") or {}
    semantic_category_counts: dict[str, int] = {}
    for category, terms in semantic_categories.items():
        semantic_category_counts[category] = count_mixed_hits(text, tokens, terms)

    return ParagraphMetricCounts(
        token_count=token_count,
        char_count=char_count,
        sentence_count=sentence_count,
        sentence_char_sum=sentence_char_sum,
        sentence_char_sum_sq=sentence_char_sum_sq,
        positive_weight_sum=positive_weight_sum,
        negative_weight_sum=negative_weight_sum,
        fight_weight_sum=fight_weight_sum,
        exclaim_count=exclaim_count,
        question_count=question_count,
        pause_count=pause_count,
        dialogue_char_count=dialogue_char_count,
        sensory_hit_count=sensory_hit_count,
        imagery_hit_count=imagery_hit_count,
        metaphor_sentence_count=metaphor_sentence_count,
        function_word_counts=function_word_counts,
        semantic_category_counts=semantic_category_counts,
    )
