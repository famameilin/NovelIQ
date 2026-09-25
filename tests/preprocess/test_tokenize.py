import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.preprocess.tokenize import Tokenizer, tokenize


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


class TestTokenizeFunction(unittest.TestCase):
    def test_tokenize_function_handles_none(self):
        result = tokenize(None)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
