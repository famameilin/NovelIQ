import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.emotion_metrics_extra import (
    compute_emotion_polarity_distribution,
    compute_emotion_recovery_speed,
    compute_pivot_moment_density,
)


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


class TestEmotionPolarityDistribution(unittest.TestCase):
    def test_empty_valences(self) -> None:
        result = compute_emotion_polarity_distribution([])
        self.assertEqual(result["positive_ratio"], 0.0)
        self.assertEqual(result["negative_ratio"], 0.0)
        self.assertEqual(result["neutral_ratio"], 0.0)

    def test_polarity_distribution_five_class(self) -> None:
        result = compute_emotion_polarity_distribution([
            "strong_positive", "mild_positive", 
            "neutral", 
            "mild_negative", "strong_negative"
        ])
        self.assertAlmostEqual(result["positive_ratio"], 0.4, places=6)
        self.assertAlmostEqual(result["negative_ratio"], 0.4, places=6)
        self.assertAlmostEqual(result["neutral_ratio"], 0.2, places=6)

    def test_polarity_distribution_only_positive(self) -> None:
        result = compute_emotion_polarity_distribution([
            "strong_positive", "mild_positive", "strong_positive"
        ])
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
