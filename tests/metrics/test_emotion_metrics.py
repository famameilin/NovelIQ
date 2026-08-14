import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.emotion_metrics import lexical_sentiment_density, pos_neg_ratio
from src.metrics.emotion_metrics_extra import (
    compute_emotion_polarity_distribution,
    compute_emotion_recovery_speed,
    compute_emotion_recovery_speed_by_position,
    compute_lexical_emotion_trend_by_position,
    compute_pivot_moment_density,
)


class TestLexicalSentimentDensity(unittest.TestCase):
    """
    测试词汇情感密度计算（phrase 模式）

    创建时间: 2026-04-06
    任务: 词表与张力信号系统重构 - Task 6
    修改时间: 2026-04-06
    修改内容: 更新参数类型为 dict[str, int]
    """

    def test_empty_text(self) -> None:
        """空文本返回零密度"""
        result = lexical_sentiment_density("", {"快乐": 1}, {"悲伤": 1})
        self.assertEqual(result["pos_density"], 0.0)
        self.assertEqual(result["neg_density"], 0.0)
        self.assertEqual(result["net_density"], 0.0)

    def test_basic_token_match(self) -> None:
        """基本 token 匹配"""
        result = lexical_sentiment_density("今天很快乐", {"快乐": 1}, {"悲伤": 1})
        self.assertGreater(result["pos_density"], 0.0)
        self.assertEqual(result["neg_density"], 0.0)

    def test_phrase_match_unsegmented_word(self) -> None:
        """
        phrase 模式匹配未登录词（被分词拆散的词）

        场景: "冷笑"被分词为"冷"+"笑"，但词表中只有"冷笑"
        期望: phrase 模式能通过子串匹配命中
        """
        result = lexical_sentiment_density("她冷笑一声", {}, {"冷笑": 1})
        self.assertGreater(result["neg_density"], 0.0)

    def test_phrase_match_multi_char_term(self) -> None:
        """
        phrase 模式匹配多字词（如"道心破碎"）

        场景: 词表中有"道心破碎"，文本中出现该词
        期望: phrase 模式能命中
        """
        result = lexical_sentiment_density("他道心破碎，万念俱灰", {}, {"道心破碎": 1})
        self.assertGreater(result["neg_density"], 0.0)

    def test_net_density_calculation(self) -> None:
        """净密度计算正确"""
        result = lexical_sentiment_density("快乐和悲伤", {"快乐": 1}, {"悲伤": 1})
        self.assertAlmostEqual(result["net_density"], 0.0, places=4)

    def test_pos_neg_ratio(self) -> None:
        """正负比例计算"""
        ratio = pos_neg_ratio("快乐快乐悲伤", {"快乐": 1}, {"悲伤": 1})
        self.assertEqual(ratio, 2.0)


class TestEmotionRecoverySpeed(unittest.TestCase):
    def test_empty_emotions(self) -> None:
        result = compute_emotion_recovery_speed([])
        self.assertIsNone(result)

    def test_no_recovery_needed(self) -> None:
        result = compute_emotion_recovery_speed([0.1, 0.1, 0.1])
        self.assertIsNone(result)

    def test_with_recovery(self) -> None:
        emotions = [0.5, -0.5, -0.3, 0.0, 0.2, 0.5]
        result = compute_emotion_recovery_speed(emotions)
        self.assertGreater(result, 0.0)


class TestEmotionRecoverySpeedByPosition(unittest.TestCase):
    """字符坐标版情绪恢复速度（设计 §10）：恢复距离用字符位置差，不用点索引差。"""

    def test_empty_emotions_returns_zero(self) -> None:
        self.assertEqual(compute_emotion_recovery_speed_by_position([], []), 0.0)

    def test_len_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_emotion_recovery_speed_by_position([0.0, 0.5, 1.0], [0.5, -0.5])

    def test_recovery_uses_char_position_distance(self) -> None:
        positions = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
        scores = [0.5, -0.5, -0.3, 0.0, 0.2, 0.5]
        # 低谷 1 恢复到位置 0.3：0.3-0.1=0.2；低谷 2 恢复到位置 0.3：0.3-0.2=0.1；
        # 平均 0.15（点索引口径则为 (2+1)/2=1.5）。
        result = compute_emotion_recovery_speed_by_position(positions, scores)
        self.assertAlmostEqual(result, 0.15, places=6)

    def test_recovery_with_uneven_positions(self) -> None:
        positions = [0.0, 0.5, 0.55, 0.6, 0.7, 1.0]
        scores = [0.5, -0.5, -0.3, 0.0, 0.2, 0.5]
        # 距离变为字符差：0.6-0.5=0.1 与 0.6-0.55=0.05，平均 0.075。
        result = compute_emotion_recovery_speed_by_position(positions, scores)
        self.assertAlmostEqual(result, 0.075, places=6)

    def test_no_recovery_returns_zero(self) -> None:
        self.assertEqual(
            compute_emotion_recovery_speed_by_position([0.0, 0.5, 1.0], [0.1, 0.1, 0.1]),
            0.0,
        )


class TestLexicalEmotionTrendByPosition(unittest.TestCase):
    """字符坐标版前中后趋势（设计 §10）：三等分按字符区间 [0, 1/3)、[1/3, 2/3)、[2/3, 1]。"""

    def test_short_input_returns_stable(self) -> None:
        result = compute_lexical_emotion_trend_by_position([0.0, 0.5], [0.1, 0.2])
        self.assertEqual(result["trend"], "stable")
        self.assertEqual(result["first_avg"], 0.0)
        self.assertEqual(result["stdev"], 0.0)

    def test_segments_split_by_char_position(self) -> None:
        # 字符区间边界 = 0 + 1/3 ≈ 0.3333 与 2/3 ≈ 0.6667：
        # 前段 = {0.0, 0.29}，中段 = {0.35, 0.59}，后段 = {0.70, 1.0}。
        positions = [0.0, 0.29, 0.35, 0.59, 0.70, 1.0]
        scores = [0.0, 0.0, 1.0, 1.0, 2.0, 2.0]
        result = compute_lexical_emotion_trend_by_position(positions, scores)
        self.assertEqual(result["first_avg"], 0.0)
        self.assertAlmostEqual(result["middle_avg"], 1.0, places=6)
        self.assertAlmostEqual(result["last_avg"], 2.0, places=6)

    def test_rising_trend(self) -> None:
        positions = [i / 9 for i in range(10)]
        scores = [0.001] * 5 + [0.0031] * 5
        result = compute_lexical_emotion_trend_by_position(positions, scores)
        self.assertAlmostEqual(result["first_avg"], 0.001, places=6)
        self.assertAlmostEqual(result["middle_avg"], 0.0017, places=6)
        self.assertAlmostEqual(result["last_avg"], 0.0031, places=6)
        self.assertLess(result["stdev"], 0.003)
        self.assertEqual(result["trend"], "rising")

    def test_falling_trend(self) -> None:
        positions = [i / 9 for i in range(10)]
        scores = [0.0031] * 5 + [0.001] * 5
        result = compute_lexical_emotion_trend_by_position(positions, scores)
        self.assertEqual(result["trend"], "falling")

    def test_volatile_trend(self) -> None:
        positions = [i / 9 for i in range(10)]
        scores = [0.01, 0.0, 0.01, 0.0, 0.01, 0.0, 0.01, 0.0, 0.01, 0.0]
        result = compute_lexical_emotion_trend_by_position(positions, scores)
        self.assertEqual(result["trend"], "volatile")

    def test_len_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_lexical_emotion_trend_by_position([0.0, 0.5, 1.0], [0.1, 0.2])


class TestEmotionPolarityDistribution(unittest.TestCase):
    def test_empty_valences(self) -> None:
        result = compute_emotion_polarity_distribution([])
        self.assertEqual(result["positive_ratio"], 0.0)
        self.assertEqual(result["negative_ratio"], 0.0)
        self.assertEqual(result["neutral_ratio"], 0.0)

    def test_polarity_distribution_five_class(self) -> None:
        result = compute_emotion_polarity_distribution(
            ["strong_positive", "mild_positive", "neutral", "mild_negative", "strong_negative"]
        )
        self.assertAlmostEqual(result["positive_ratio"], 0.4, places=6)
        self.assertAlmostEqual(result["negative_ratio"], 0.4, places=6)
        self.assertAlmostEqual(result["neutral_ratio"], 0.2, places=6)

    def test_polarity_distribution_only_positive(self) -> None:
        result = compute_emotion_polarity_distribution(["strong_positive", "mild_positive", "strong_positive"])
        self.assertAlmostEqual(result["positive_ratio"], 1.0, places=6)
        self.assertAlmostEqual(result["negative_ratio"], 0.0, places=6)
        self.assertAlmostEqual(result["neutral_ratio"], 0.0, places=6)


class TestPivotMomentDensity(unittest.TestCase):
    def test_empty_pivot_moments(self) -> None:
        result = compute_pivot_moment_density([])
        self.assertEqual(result, 0.0)

    def test_all_pivots(self) -> None:
        result = compute_pivot_moment_density([1, 1, 1])
        self.assertEqual(result, 1.0)

    def test_partial_pivots(self) -> None:
        result = compute_pivot_moment_density([1, 0, 1, 0, 0])
        self.assertEqual(result, 0.4)


if __name__ == "__main__":
    unittest.main()
