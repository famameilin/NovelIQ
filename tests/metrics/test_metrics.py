"""Metrics 模块测试"""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.lexicon_metrics import (
    count_mixed_hits,
    term_mixed_counts,
)
from src.metrics.style_metrics import mtld, ttr
from src.text_processing.text_utils import dialogue_length, split_sentences, tokenize_words


class TestLexiconMetrics(unittest.TestCase):
    def test_count_mixed_hits_basic(self) -> None:
        text = "斩击斩击爆裂"
        tokens = ["斩击", "斩击", "爆裂"]
        hits = count_mixed_hits(text, tokens, ["斩击", "爆裂", "格挡"])
        self.assertEqual(hits, 3)

    def test_count_mixed_hits_empty_text(self) -> None:
        hits = count_mixed_hits("", [], ["斩击"])
        self.assertEqual(hits, 0)

    def test_count_mixed_hits_phrase_mode(self) -> None:
        text = "青衫剑客踏月而来"
        tokens = ["青衫", "剑客", "踏月", "而来"]
        hits = count_mixed_hits(text, tokens, ["青衫剑客"])
        self.assertEqual(hits, 1)

    def test_count_mixed_hits_no_overlap(self) -> None:
        text = "渡劫飞升"
        tokens = ["渡劫", "飞升"]
        hits = count_mixed_hits(text, tokens, ["渡劫", "飞升", "渡劫飞升"])
        self.assertEqual(hits, 1)

    def test_term_mixed_counts(self) -> None:
        text = "斩击爆裂斩击"
        tokens = ["斩击", "爆裂", "斩击"]
        counts = term_mixed_counts(text, tokens, ["斩击", "爆裂"])
        self.assertEqual(counts["斩击"], 2)
        self.assertEqual(counts["爆裂"], 1)


class TestTextUtils(unittest.TestCase):
    def test_split_sentences(self) -> None:
        text = "你好！我来了。好么？\n行"
        self.assertEqual(split_sentences(text), ["你好", "我来了", "好么", "行"])

    def test_dialogue_length(self) -> None:
        text = '他说：「你好」然后说"再见"'
        self.assertEqual(dialogue_length(text), 4)

    def test_tokenize_words(self) -> None:
        text = "你好世界"
        tokens = tokenize_words(text)
        self.assertGreaterEqual(len(tokens), 2)


class TestStyleMetrics(unittest.TestCase):
    def test_mtld_ttr(self) -> None:
        tokens = ["我", "爱", "你", "我", "爱", "他"]
        self.assertGreater(ttr(tokens), 0)
        self.assertGreater(mtld(tokens), 0)

    def test_mtld_factors_zero_returns_none(self) -> None:
        # 全唯一词（TTR 未跌破阈值）时 MTLD 数学上无定义，返回 None
        tokens = ["我", "爱", "你"]
        self.assertIsNone(mtld(tokens))

    def test_mtld_empty_tokens(self) -> None:
        self.assertEqual(mtld([]), 0.0)


if __name__ == "__main__":
    unittest.main()
