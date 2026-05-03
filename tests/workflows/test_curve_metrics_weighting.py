"""
词汇情绪曲线加权逻辑测试

创建时间: 2026-04-21
任务: fix-emotion-curve-weighting
说明: 锁定多 genre 情绪曲线在低权重场景下仍能保留有效贡献，避免词条被提前归零
"""

from src.workflows.curve_metrics import WeightedLexiconSet, compute_emotion_curve_weighted


def test_compute_emotion_curve_weighted_preserves_low_weight_hits() -> None:
    chunk_texts = [(0, "孝敬"), (1, "平静")]
    weighted_lexicons = [
        WeightedLexiconSet(
            pos_terms={"孝敬": 1.0},
            neg_terms={},
            fight_terms={},
            weight=0.25,
            genre="custom-low-positive",
        ),
        WeightedLexiconSet(
            pos_terms={},
            neg_terms={"平静": 1.0},
            fight_terms={},
            weight=0.75,
            genre="custom-negative",
        ),
    ]

    emotion_rows, raw_densities = compute_emotion_curve_weighted(chunk_texts, weighted_lexicons)

    assert len(emotion_rows) == 2
    assert raw_densities[0] > 0
    assert emotion_rows[0][1] > 0
    assert emotion_rows[0][2] == 0


def test_compute_emotion_curve_weighted_keeps_chunk_order_when_merging() -> None:
    chunk_texts = [(7, "鼓舞"), (8, "惊惧")]
    weighted_lexicons = [
        WeightedLexiconSet(
            pos_terms={"鼓舞": 1.0},
            neg_terms={},
            fight_terms={},
            weight=0.6,
            genre="custom-positive",
        ),
        WeightedLexiconSet(
            pos_terms={},
            neg_terms={"惊惧": 1.0},
            fight_terms={},
            weight=0.4,
            genre="custom-negative",
        ),
    ]

    emotion_rows, _ = compute_emotion_curve_weighted(chunk_texts, weighted_lexicons)

    assert [row[0] for row in emotion_rows] == [7, 8]
    assert emotion_rows[0][1] > 0
    assert emotion_rows[1][2] > 0
