import sys
from pathlib import Path
import unittest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.emotion_metrics import (
    lexical_sentiment_density,
    moving_average,
    pos_neg_ratio,
)
from src.metrics.lexicon_metrics import (
    count_hits,
    count_token_hits,
    density,
    term_counts,
    token_density,
)
from src.metrics.rhythm_metrics import tension_composite, tension_proxy
from src.metrics.style_metrics import (
    average_word_length,
    dialogue_ratio,
    function_word_distribution,
    imagery_density,
    load_function_words,
    metaphor_density,
    mtld,
    pause_density,
    sentence_length_stats,
    semantic_category_density,
    ttr,
    word_frequency_breadth,
    FUNCTION_WORDS_PATH,
)
from src.metrics.text_utils import dialogue_length, split_sentences, tokenize_words


class TestLexiconMetrics(unittest.TestCase):
    def test_term_counts(self) -> None:
        text = "斩击斩击爆裂"
        counts = term_counts(text, ["斩击", "爆裂", "格挡"])
        self.assertEqual(counts["斩击"], 2)
        self.assertEqual(counts["爆裂"], 1)
        self.assertNotIn("格挡", counts)

    def test_density_empty(self) -> None:
        self.assertEqual(density("", ["斩击"]), 0.0)

    def test_count_hits(self) -> None:
        text = "斩击爆裂斩击"
        self.assertEqual(count_hits(text, ["斩击", "爆裂"]), 3)

    def test_token_density(self) -> None:
        tokens = ["斩击", "爆裂", "斩击"]
        self.assertEqual(count_token_hits(tokens, ["斩击"]), 2)
        self.assertAlmostEqual(token_density(tokens, ["斩击"]), 2 / 3, places=6)


class TestTextUtils(unittest.TestCase):
    def test_split_sentences(self) -> None:
        text = "你好！我来了。好么？\n行"
        self.assertEqual(split_sentences(text), ["你好", "我来了", "好么", "行"])

    def test_dialogue_length(self) -> None:
        text = "他说：「你好」然后说\"再见\""
        self.assertEqual(dialogue_length(text), 4)

    def test_tokenize_words(self) -> None:
        text = "你好世界"
        tokens = tokenize_words(text)
        self.assertGreaterEqual(len(tokens), 2)


class TestEmotionMetrics(unittest.TestCase):
    def test_lexical_sentiment_density(self) -> None:
        text = "good bad good"
        result = lexical_sentiment_density(text, ["good"], ["bad"])
        self.assertGreater(result["pos_density"], 0)
        self.assertGreater(result["neg_density"], 0)
        self.assertGreater(pos_neg_ratio(text, ["good"], ["bad"]), 0)
        self.assertEqual(moving_average([1.0, 2.0, 3.0], 2), [1.0, 1.5, 2.5])


class TestRhythmMetrics(unittest.TestCase):
    def test_tension_proxy(self) -> None:
        text = "「杀」！斩击。你好吗？"
        result = tension_proxy(text, ["斩击", "杀"])
        self.assertGreater(result["avg_sent_len"], 0)
        self.assertGreater(result["fight_density"], 0)
        self.assertGreater(result["dialogue_ratio"], 0)
        self.assertGreater(result["question_density"], 0)
        self.assertGreaterEqual(result["exclaim_density"], 0)
        composite = tension_composite([result, result])
        self.assertEqual(len(composite), 2)


class TestStyleMetrics(unittest.TestCase):
    def test_sentence_length_stats(self) -> None:
        stats = sentence_length_stats("你好。再见。")
        self.assertGreater(stats["avg_sent_len"], 0)

    def test_pause_density(self) -> None:
        text = "你好，世界；再见。"
        self.assertGreater(pause_density(text), 0)

    def test_metaphor_density(self) -> None:
        text = "她像风一样。"
        self.assertGreater(metaphor_density(text), 0)

    def test_mtld_ttr(self) -> None:
        tokens = ["我", "爱", "你", "我", "爱", "他"]
        self.assertGreater(ttr(tokens), 0)
        self.assertGreater(mtld(tokens), 0)
        self.assertGreater(average_word_length(tokens), 0)
        self.assertGreaterEqual(word_frequency_breadth(tokens, 0.8), 0)

    def test_function_word_distribution(self) -> None:
        tokens = ["的", "是", "我", "的"]
        dist = function_word_distribution(tokens, ["的", "是"])
        self.assertGreater(dist.get("的", 0), 0)

    def test_function_word_distribution_basic(self) -> None:
        tokens = ["我", "的", "书", "在", "桌", "子", "上"]
        function_words = ["的", "在", "上"]
        dist = function_word_distribution(tokens, function_words)
        self.assertEqual(dist["的"], 1 / 7)
        self.assertEqual(dist["在"], 1 / 7)
        self.assertEqual(dist["上"], 1 / 7)
        self.assertNotIn("我", dist)

    def test_function_word_distribution_empty_tokens(self) -> None:
        dist = function_word_distribution([], ["的", "是"])
        self.assertEqual(dist, {})

    def test_function_word_distribution_empty_function_words(self) -> None:
        tokens = ["我", "的", "书"]
        dist = function_word_distribution(tokens, [])
        self.assertEqual(dist, {})

    def test_function_word_distribution_no_matches(self) -> None:
        tokens = ["我", "爱", "你"]
        dist = function_word_distribution(tokens, ["的", "是"])
        self.assertEqual(dist, {})

    def test_function_word_distribution_relative_frequency(self) -> None:
        tokens = ["的", "的", "的", "我", "爱", "你"]
        dist = function_word_distribution(tokens, ["的"])
        self.assertAlmostEqual(dist["的"], 3 / 6, places=6)

    def test_load_function_words_default(self) -> None:
        words = load_function_words()
        self.assertIsInstance(words, list)
        self.assertGreater(len(words), 100)
        self.assertIn("的", words)
        self.assertIn("了", words)
        self.assertIn("和", words)

    def test_load_function_words_custom_path(self) -> None:
        words = load_function_words(FUNCTION_WORDS_PATH)
        self.assertGreater(len(words), 100)

    def test_load_function_words_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_function_words("nonexistent_path.txt")

    def test_function_word_distribution_integration(self) -> None:
        function_words = load_function_words()
        tokens = ["我", "的", "书", "在", "桌", "子", "上", "了"]
        dist = function_word_distribution(tokens, function_words)
        self.assertIn("的", dist)
        self.assertIn("在", dist)
        self.assertIn("了", dist)

    def test_semantic_category_density(self) -> None:
        text = "刀剑宗门"
        self.assertGreater(semantic_category_density(text, ["刀剑"]), 0)

    def test_dialogue_ratio(self) -> None:
        text = "「你好」"
        self.assertGreater(dialogue_ratio(text), 0)

    def test_imagery_density(self) -> None:
        text = "明月几时有，把酒问青天"
        terms = ["明月", "酒", "青天", "山", "水"]
        result = imagery_density(text, terms)
        self.assertGreater(result, 0)
        text2 = "今天天气真好"
        result2 = imagery_density(text2, terms)
        self.assertEqual(result2, 0.0)
        result3 = imagery_density("", terms)
        self.assertEqual(result3, 0.0)


if __name__ == "__main__":
    unittest.main()
