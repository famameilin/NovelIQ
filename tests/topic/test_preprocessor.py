import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.topic.preprocessor import TopicPreprocessor


class TestTopicPreprocessor(unittest.TestCase):
    def setUp(self) -> None:
        self.preprocessor = TopicPreprocessor()

    def test_tokenize_basic(self) -> None:
        text = "这是一个测试文本"
        tokens = self.preprocessor.tokenize(text)
        self.assertIsInstance(tokens, list)
        self.assertTrue(all(isinstance(t, str) for t in tokens))

    def test_tokenize_empty(self) -> None:
        tokens = self.preprocessor.tokenize("")
        self.assertEqual(tokens, [])

    def test_tokenize_whitespace(self) -> None:
        tokens = self.preprocessor.tokenize("   \n\t  ")
        self.assertEqual(tokens, [])

    def test_stopwords_filtered(self) -> None:
        text = "我是一个人"
        tokens = self.preprocessor.tokenize(text)
        self.assertNotIn("是", tokens)
        self.assertNotIn("我", tokens)

    def test_min_word_len(self) -> None:
        preprocessor = TopicPreprocessor(min_word_len=3)
        text = "测试文本内容"
        tokens = preprocessor.tokenize(text)
        self.assertTrue(all(len(t) >= 3 for t in tokens))

    def test_preprocess_documents(self) -> None:
        docs = ["这是第一段文本", "这是第二段文本"]
        results = self.preprocessor.preprocess_documents(docs)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(isinstance(r, list) for r in results))

    def test_add_stopwords(self) -> None:
        self.preprocessor.add_stopwords(["测试词"])
        self.assertIn("测试词", self.preprocessor.stopwords)

    def test_stopwords_property(self) -> None:
        stopwords = self.preprocessor.stopwords
        self.assertIsInstance(stopwords, set)
        self.assertIn("的", stopwords)


class TestTopicPreprocessorWithUserDict(unittest.TestCase):
    def test_user_dict_loading(self) -> None:
        with patch("jieba.load_userdict") as mock_load:
            mock_path = Path("/fake/dict.txt")
            with patch.object(Path, "exists", return_value=True):
                preprocessor = TopicPreprocessor(user_dict_path=mock_path)
                preprocessor.tokenize("测试")
                mock_load.assert_called_once_with(str(mock_path))


if __name__ == "__main__":
    unittest.main()
