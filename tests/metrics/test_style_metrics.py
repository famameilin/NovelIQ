import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.style_metrics_extra import (
    compute_idiom_density,
    compute_classical_sentence_ratio,
)


class TestIdiomDensity(unittest.TestCase):
    def test_empty_texts(self) -> None:
        result = compute_idiom_density([])
        self.assertEqual(result, 0.0)

    def test_with_idioms(self) -> None:
        result = compute_idiom_density(["一心一意", "三心二意"])
        self.assertGreater(result, 0.0)


class TestClassicalSentenceRatio(unittest.TestCase):
    def test_empty_texts(self) -> None:
        result = compute_classical_sentence_ratio([])
        self.assertEqual(result, 0.0)

    def test_with_classical_sentences(self) -> None:
        result = compute_classical_sentence_ratio(["此乃天意也。", "岂不美哉？"])
        self.assertGreater(result, 0.0)

    def test_modern_sentences(self) -> None:
        result = compute_classical_sentence_ratio(["这是现代汉语。", "今天天气很好。"])
        self.assertEqual(result, 0.0)


if __name__ == "__main__":
    unittest.main()
