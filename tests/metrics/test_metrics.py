"""
Metrics 模块测试

修改时间: 2026-04-06
任务: 移除向后兼容代码
修改内容: 移除旧版精确匹配函数测试，保留 phrase 模式匹配测试
"""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.emotion_metrics import (
    lexical_sentiment_density,
    pos_neg_ratio,
)
from src.metrics.lexicon_metrics import (
    count_mixed_hits,
    term_mixed_counts,
)
from src.metrics.rhythm_metrics import tension_composite, tension_proxy
from src.metrics.style_metrics import (
    FUNCTION_WORDS_PATH,
    average_word_length,
    dialogue_ratio,
    function_word_distribution,
    imagery_density,
    load_function_words,
    metaphor_density,
    mtld,
    pause_density,
    semantic_category_density,
    sentence_length_stats,
    ttr,
    word_frequency_breadth,
)
from src.metrics.text_utils import dialogue_length, split_sentences, tokenize_words


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


class TestEmotionMetrics(unittest.TestCase):
    def test_lexical_sentiment_density(self) -> None:
        text = "good bad good"
        result = lexical_sentiment_density(text, {"good": 1}, {"bad": 1})
        self.assertGreater(result["pos_density"], 0)
        self.assertGreater(result["neg_density"], 0)
        self.assertGreater(pos_neg_ratio(text, {"good": 1}, {"bad": 1}), 0)


class TestRhythmMetrics(unittest.TestCase):
    def test_tension_proxy(self) -> None:
        text = "「杀」！斩击。你好吗？"
        result = tension_proxy(text, {"斩击": 1, "杀": 1})
        self.assertGreater(result["avg_sent_len"], 0)
        self.assertGreater(result["fight_density"], 0)
        self.assertGreater(result["dialogue_ratio"], 0)
        self.assertGreater(result["question_density"], 0)
        self.assertGreaterEqual(result["exclaim_density"], 0)
        composite = tension_composite(
            result["fight_density"],
            result["exclaim_density"],
            result["question_density"],
            result["dialogue_ratio"],
            result["avg_sent_len"],
        )
        self.assertGreaterEqual(composite, 0)

    def test_tension_proxy_no_overlap_count(self) -> None:
        """
        修改时间: 2026-03-26
        任务: 修复 fight_density 重叠计数问题
        修改内容: 新增测试用例，验证重叠词不被重复计数
        """
        text = "仙道杀招"
        result = tension_proxy(text, {"杀招": 1, "道杀招": 1, "仙道杀招": 1})
        tokens = tokenize_words(text)
        self.assertEqual(len(tokens), 2)
        self.assertAlmostEqual(result["fight_density"], 1.0 / len(tokens), places=6)


class TestStyleMetrics(unittest.TestCase):
    def test_sentence_length_stats(self) -> None:
        stats = sentence_length_stats("你好。再见。")
        self.assertGreater(stats["avg_sent_len"], 0)
        # §19.5: d_value 与 sent_len_std 完全重复，已移除
        self.assertNotIn("d_value", stats)
        self.assertIn("sent_len_std", stats)
        self.assertEqual(
            stats["sent_len_std"],
            sentence_length_stats("你好。再见。")["sent_len_std"],
        )

    def test_sentence_length_stats_empty(self) -> None:
        stats = sentence_length_stats("")
        self.assertEqual(stats["avg_sent_len"], 0.0)
        self.assertEqual(stats["sent_len_std"], 0.0)
        self.assertNotIn("d_value", stats)

    def test_pause_density(self) -> None:
        text = "你好，世界；再见。"
        self.assertGreater(pause_density(text), 0)

    def test_pause_density_per_hundred_chars(self) -> None:
        # §19.4: 每百字停顿频率，随长度线性增长而非二次增长
        text_short = "你，你。"
        text_long = text_short * 10
        self.assertAlmostEqual(pause_density(text_short), pause_density(text_long), places=6)
        text_empty = ""
        self.assertEqual(pause_density(text_empty), 0.0)
        text_no_pause = "你好世界"
        self.assertEqual(pause_density(text_no_pause), 0.0)

    def test_metaphor_density(self) -> None:
        text = "她像风一样。"
        self.assertGreater(metaphor_density(text), 0)

    def test_mtld_ttr(self) -> None:
        tokens = ["我", "爱", "你", "我", "爱", "他"]
        self.assertGreater(ttr(tokens), 0)
        self.assertGreater(mtld(tokens), 0)
        self.assertGreater(average_word_length(tokens), 0)
        self.assertGreaterEqual(word_frequency_breadth(tokens, 0.8), 0)

    def test_mtld_factors_zero_returns_none(self) -> None:
        # §19.12: 全唯一词（TTR 未跌破阈值）时 MTLD 数学上无定义，返回 None
        tokens = ["我", "爱", "你"]
        self.assertIsNone(mtld(tokens))

    def test_mtld_empty_tokens(self) -> None:
        self.assertEqual(mtld([]), 0.0)

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
