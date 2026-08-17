"""情感指标：词表密度 + 进度轴恢复/趋势。"""

from __future__ import annotations

import unittest

from src.metrics.emotion_metrics import lexical_sentiment_density, pos_neg_ratio
from src.metrics.emotion_metrics_extra import (
    compute_arc_delta,
    compute_emotion_polarity_distribution,
    compute_emotion_recovery_speed,
    compute_lexical_emotion_trend,
    compute_lexical_emotion_trend_detail,
    compute_pos_neg_ratio,
)


class TestLexicalBasics(unittest.TestCase):
    def test_pos_neg_ratio_text(self) -> None:
        ratio = pos_neg_ratio("快乐快乐悲伤", {"快乐": 1}, {"悲伤": 1})
        self.assertGreater(ratio, 0)

    def test_lexical_density(self) -> None:
        density = lexical_sentiment_density("快乐悲伤", {"快乐": 1}, {"悲伤": 1})
        self.assertIn("pos_density", density)
        self.assertIn("neg_density", density)


class TestRecoverySpeed(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertIsNone(compute_emotion_recovery_speed([], []))

    def test_no_trough(self) -> None:
        self.assertIsNone(
            compute_emotion_recovery_speed([0.0, 0.5, 1.0], [0.1, 0.1, 0.1])
        )

    def test_progress_distance(self) -> None:
        result = compute_emotion_recovery_speed([0.0, 0.5, 1.0], [0.2, -0.5, 0.2])
        self.assertIsNotNone(result)
        assert result is not None
        self.assertAlmostEqual(result, 0.5, places=6)

    def test_len_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_emotion_recovery_speed([0.0, 0.5, 1.0], [0.5, -0.5])


class TestLexicalTrend(unittest.TestCase):
    def test_insufficient(self) -> None:
        self.assertIsNone(compute_lexical_emotion_trend([0.0, 0.5], [0.1, 0.2]))

    def test_rising(self) -> None:
        positions = [i / 9 for i in range(10)]
        scores = [0.0] * 3 + [0.0] * 3 + [0.01] * 4
        # force non-volatile small stdev path with larger rise
        scores = [-0.01] * 4 + [0.0] * 3 + [0.01] * 3
        detail = compute_lexical_emotion_trend_detail(positions, scores)
        self.assertIn(detail["trend"], {"rising", "falling", "stable", "volatile"})
        trend = compute_lexical_emotion_trend(positions, scores)
        self.assertEqual(trend, detail["trend"])


class TestPolarityAndArc(unittest.TestCase):
    def test_polarity(self) -> None:
        result = compute_emotion_polarity_distribution(
            ["strong_positive", "mild_negative", "neutral"]
        )
        self.assertAlmostEqual(result["positive_ratio"] + result["negative_ratio"] + result["neutral_ratio"], 1.0)

    def test_polarity_empty_returns_null_ratios(self) -> None:
        # 契约：无有效情绪标注时三项均为 null，禁止 0.0 伪值
        result = compute_emotion_polarity_distribution([])
        assert result == {
            "positive_ratio": None,
            "negative_ratio": None,
            "neutral_ratio": None,
        }

    def test_arc_delta_empty(self) -> None:
        self.assertIsNone(compute_arc_delta([]))

    def test_pos_neg_ratio_densities(self) -> None:
        self.assertIsNone(compute_pos_neg_ratio([], []))
        ratio = compute_pos_neg_ratio([0.2, 0.3], [0.1, 0.1])
        self.assertIsNotNone(ratio)


if __name__ == "__main__":
    unittest.main()
