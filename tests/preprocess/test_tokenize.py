import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.text_processing.tokenize import Tokenizer, reuse_token_blocks, tokenize


class TestTokenizer(unittest.TestCase):
    def setUp(self):
        Tokenizer._instance = None
        Tokenizer._initialized = False

    def test_tokenize_basic(self):
        text = "我喜欢学习中文"
        result = tokenize(text)
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)

    def test_tokenize_empty_string(self):
        result = tokenize("")
        self.assertEqual(result, [])

    def test_tokenize_whitespace_only(self):
        result = tokenize("   \t\n  ")
        self.assertEqual(result, [])

    def test_tokenize_with_mixed_content(self):
        text = "这是test123测试"
        result = tokenize(text)
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)

    def test_tokenizer_min_word_len(self):
        Tokenizer._instance = None
        Tokenizer._initialized = False
        tokenizer = Tokenizer(min_word_len=2)
        text = "我是个好人"
        result = tokenizer.tokenize(text)
        for token in result:
            self.assertGreaterEqual(len(token), 2)

    def test_tokenizer_filter_stopwords(self):
        Tokenizer._instance = None
        Tokenizer._initialized = False
        tokenizer = Tokenizer(stopwords_path=None)
        tokenizer._stopwords = {"的", "是", "了"}
        text = "我是好人"
        result_with_stopwords = tokenizer.tokenize(text, filter_stopwords=False)
        result_without_stopwords = tokenizer.tokenize(text, filter_stopwords=True)
        self.assertTrue(len(result_with_stopwords) >= len(result_without_stopwords))

    def test_tokenizer_add_stopwords(self):
        Tokenizer._instance = None
        Tokenizer._initialized = False
        tokenizer = Tokenizer()
        initial_count = len(tokenizer.stopwords)
        tokenizer.add_stopwords(["测试词1", "测试词2"])
        self.assertEqual(len(tokenizer.stopwords), initial_count + 2)

    def test_shared_book_tokenization_matches_independent_inputs(self):
        tokenizer = Tokenizer()
        chapters = ["", "南京市长", "", "江大桥。", "A-", "B\r", "\n！第", "三章", ""]
        actual_chapters, actual_book = tokenizer.tokenize_chapters_and_book(chapters)
        self.assertEqual(actual_chapters, [tokenizer.tokenize(text) for text in chapters])
        self.assertEqual(actual_book, tokenizer.tokenize("".join(chapters)))

    def test_request_blocks_preserve_mixed_text_and_cross_chapter_boundaries(self):
        tokenizer = Tokenizer()
        tokenizer._stopwords = {"南京市", "的"}
        chapters = ["", "南京市长", "江大桥。\r\n", "test-ABC 42", "\n", "南京市长江大桥！"]
        expected = [tokenizer.tokenize(text, filter_stopwords=True) for text in chapters]
        expected_lengths = [tokenizer.tokenize_with_word_lengths(text) for text in chapters]
        expected_chapters, expected_book = tokenizer.tokenize_chapters_and_book(chapters)

        with reuse_token_blocks():
            self.assertEqual([tokenizer.tokenize(text, filter_stopwords=True) for text in chapters], expected)
            self.assertEqual([tokenizer.tokenize_with_word_lengths(text) for text in chapters], expected_lengths)
            self.assertEqual(tokenizer.tokenize_chapters_and_book(chapters), (expected_chapters, expected_book))

        self.assertEqual(tokenizer.tokenize_chapters_and_book(chapters), (expected_chapters, expected_book))


class TestTokenizeFunction(unittest.TestCase):
    def test_tokenize_function_handles_none(self):
        result = tokenize(None)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
