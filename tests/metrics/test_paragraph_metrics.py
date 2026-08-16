"""
段落级指标原始计数与充分统计量测试（设计《章节粒度分析指标重设计》§5.3）

逐字段断言 compute_paragraph_metric_counts 的 17 个字段：
构造确定文本，覆盖否定翻转（单重/双重）、充分统计量手工核算、
对话长度、空文本/空词表全零、缺失词表键按空处理。
"""

from __future__ import annotations

import pytest

from src.metrics.paragraph_metrics import (
    ParagraphMetricCounts,
    compute_paragraph_metric_counts,
)

TEXT = "他很快乐，也很痛苦。不快乐的时候，他像花朵一样凋零！他在战斗中咆哮，真的吗？"
TOKENS = [
    "他", "很", "快乐", "也", "很", "痛苦", "不", "快乐", "的", "时候",
    "他", "像", "花朵", "一样", "凋零", "他", "在", "战斗", "中", "咆哮", "真的", "吗",
]
LEXICONS = {
    "pos_terms": {"快乐": 1.0},
    "neg_terms": {"痛苦": 1.0},
    "fight_terms": {"战斗": 1.0},
    "sensory": ["花朵"],
    "imagery": ["凋零"],
    "function_words": ["的", "了", "吗", "在"],
    "semantic_categories": {"emotion": ["快乐", "痛苦"], "combat": ["战斗", "咆哮"]},
}


def test_compute_paragraph_metric_counts_full_fields() -> None:
    """综合文本：逐字段断言全部计数与充分统计量"""
    counts = compute_paragraph_metric_counts(TEXT, TOKENS, LEXICONS)
    assert isinstance(counts, ParagraphMetricCounts)

    # 1. 基础计数
    assert counts.token_count == 22
    assert counts.char_count == 38

    # 2. 句长充分统计量（手工核算：9 / 15 / 11 三个句子）
    assert counts.sentence_count == 3
    assert counts.sentence_char_sum == pytest.approx(35.0)
    assert counts.sentence_char_sum_sq == pytest.approx(427.0)

    # 3. 正负情绪分子（命中计数 + 否定翻转）：快乐 正向1次 + 不快乐 翻转负向1次 + 痛苦 负向1次
    assert counts.positive_weight_sum == pytest.approx(1.0)
    assert counts.negative_weight_sum == pytest.approx(2.0)

    # 4. 战斗词加权和（权重统一 1.0，fuzzy 模式）
    assert counts.fight_weight_sum == pytest.approx(1.0)

    # 5. 标点计数
    assert counts.exclaim_count == 1
    assert counts.question_count == 1
    assert counts.pause_count == 3

    # 6. 对话字符（综合文本无引号）
    assert counts.dialogue_char_count == 0

    # 7. 感官/意象命中
    assert counts.sensory_hit_count == 1
    assert counts.imagery_hit_count == 1

    # 8. 比喻句（"像花朵"所在句命中 markers）
    assert counts.metaphor_sentence_count == 1

    # 9. 虚词计数（非密度）：的 1 / 在 1 / 吗 1，了 未出现不收录
    assert counts.function_word_counts == {"的": 1, "在": 1, "吗": 1}

    # 10. 语义类别计数（非密度）：emotion 快乐×2+痛苦=3，combat 战斗+咆哮=2
    assert counts.semantic_category_counts == {"emotion": 3, "combat": 2}


def test_sentence_sufficient_statistics_manual() -> None:
    """句长充分统计量单独手工核算"""
    text = "第一句。第二句很长很长！第三句？"
    counts = compute_paragraph_metric_counts(text, ["第一句", "第二句很长很长", "第三句"], {})
    assert counts.sentence_count == 3
    assert counts.sentence_char_sum == pytest.approx(3 + 7 + 3)
    assert counts.sentence_char_sum_sq == pytest.approx(9 + 49 + 9)


def test_negation_flip_single() -> None:
    """单重否定翻转："不快乐" 计入 negative"""
    counts = compute_paragraph_metric_counts(
        "他不快乐。", ["他", "不", "快乐"], {"pos_terms": {"快乐": 1.0}}
    )
    assert counts.positive_weight_sum == pytest.approx(0.0)
    assert counts.negative_weight_sum == pytest.approx(1.0)


def test_negation_flip_double() -> None:
    """双重否定还原："不是不快乐"（两个否定词）仍计入 positive"""
    counts = compute_paragraph_metric_counts(
        "他不是不快乐。", ["他", "不是", "不", "快乐"], {"pos_terms": {"快乐": 1.0}}
    )
    assert counts.positive_weight_sum == pytest.approx(1.0)
    assert counts.negative_weight_sum == pytest.approx(0.0)


def test_negation_flip_negative_term() -> None:
    """否定翻转同样作用于负面词："不痛苦" 计入 positive"""
    counts = compute_paragraph_metric_counts(
        "他不痛苦。", ["他", "不", "痛苦"], {"neg_terms": {"痛苦": 1.0}}
    )
    assert counts.positive_weight_sum == pytest.approx(1.0)
    assert counts.negative_weight_sum == pytest.approx(0.0)


def test_dialogue_char_count() -> None:
    """对话字符数：「」角引号 + 英文双引号内容合计"""
    text = "「你好，世界。」他说：\"你好\"！"
    counts = compute_paragraph_metric_counts(text, ["你好", "世界", "他说", "你好"], {})
    assert counts.dialogue_char_count == 8


def test_empty_text_all_zero() -> None:
    """空文本 + 空词表：全部字段为零/空 dict，不抛异常"""
    counts = compute_paragraph_metric_counts("", [], {})
    assert counts.token_count == 0
    assert counts.char_count == 0
    assert counts.sentence_count == 0
    assert counts.sentence_char_sum == 0.0
    assert counts.sentence_char_sum_sq == 0.0
    assert counts.positive_weight_sum == 0.0
    assert counts.negative_weight_sum == 0.0
    assert counts.fight_weight_sum == 0.0
    assert counts.exclaim_count == 0
    assert counts.question_count == 0
    assert counts.pause_count == 0
    assert counts.dialogue_char_count == 0
    assert counts.sensory_hit_count == 0
    assert counts.imagery_hit_count == 0
    assert counts.metaphor_sentence_count == 0
    assert counts.function_word_counts == {}
    assert counts.semantic_category_counts == {}


def test_empty_lexicons_non_empty_text() -> None:
    """词表键缺失/为空按空处理：基础计数照常，词表相关字段为零"""
    counts = compute_paragraph_metric_counts("你好，世界！", ["你好", "世界"], {})
    assert counts.char_count == 6
    assert counts.exclaim_count == 1
    assert counts.pause_count == 1
    assert counts.positive_weight_sum == 0.0
    assert counts.negative_weight_sum == 0.0
    assert counts.fight_weight_sum == 0.0
    assert counts.sensory_hit_count == 0
    assert counts.imagery_hit_count == 0
    assert counts.function_word_counts == {}
    assert counts.semantic_category_counts == {}


def test_semantic_categories_without_hits() -> None:
    """语义类别给出但无命中：类别键保留、计数为 0"""
    counts = compute_paragraph_metric_counts(
        "你好。", ["你好"],
        {"semantic_categories": {"emotion": ["快乐"], "combat": ["战斗"]}},
    )
    assert counts.semantic_category_counts == {"emotion": 0, "combat": 0}
