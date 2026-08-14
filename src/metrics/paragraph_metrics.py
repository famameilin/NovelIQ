"""
段落级指标原始计数与充分统计量（设计文档《章节粒度分析指标重设计》§5.3）

本模块只产出"分子/分母"口径的原始计数与充分统计量，不计算任何密度：
密度由上层按 run 汇总后另行计算（分母为零是合法观测，调用方负责）。

与 `src.storage.repositories.paragraph_repository.ParagraphMetricRow`
（§5.3 paragraph_metrics 表）一一对应，缺 paragraph_id 与 surface_tension 系列。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.metrics.emotion_metrics import count_negations_before, load_negation_words
from src.metrics.lexicon_metrics import count_mixed_hits, get_emotion_spans
from src.metrics.matching import count_token_hits_enhanced
from src.metrics.text_utils import dialogue_length, split_sentences

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
    """
    计算段落级原始计数与充分统计量

    lexicons 键（缺失按空处理）：
        pos_terms / neg_terms: dict[str, float]，正/负面情感词及权重
        fight_terms: dict[str, float]，战斗词及权重（本模块统一按 1.0 计）
        sensory / imagery: list[str]，感官词 / 意象词
        function_words: list[str]，虚词表
        semantic_categories: dict[str, list[str]]，语义类别词表

    情绪计数实现否定翻转（逻辑与 emotion_metrics.lexical_sentiment_density
    的分子部分一致，此处返回加权和而不是密度）；否定词表经
    load_negation_words() 加载，空文本/空词表不触发表读取。
    """
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
        negation_words = load_negation_words()
        for start, _end, term in pos_spans:
            weight = float(pos_terms.get(term, 1))
            if count_negations_before(text, start, negation_words) % 2 == 1:
                negative_weight_sum += weight
            else:
                positive_weight_sum += weight
        for start, _end, term in neg_spans:
            weight = float(neg_terms.get(term, 1))
            if count_negations_before(text, start, negation_words) % 2 == 1:
                positive_weight_sum += weight
            else:
                negative_weight_sum += weight

    fight_terms = lexicons.get("fight_terms") or {}
    fight_weight_sum = float(
        count_token_hits_enhanced(text, tokens, list(fight_terms.keys()), mode="fuzzy")
    )

    exclaim_count = text.count("!") + text.count("！")
    question_count = text.count("?") + text.count("？")
    pause_count = len(_PAUSE_PATTERN.findall(text))

    dialogue_char_count = dialogue_length(text)

    sensory = lexicons.get("sensory") or []
    imagery = lexicons.get("imagery") or []
    sensory_hit_count = count_mixed_hits(text, tokens, sensory)
    imagery_hit_count = count_mixed_hits(text, tokens, imagery)

    metaphor_sentence_count = sum(
        1 for sentence in sentences if any(marker in sentence for marker in METAPHOR_MARKERS)
    )

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
