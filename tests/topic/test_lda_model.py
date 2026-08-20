import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.topic.lda_model import LDAConfig, LDATrainer, get_all_topic_words, get_topic_words
from src.topic.schema import TopicModel, TopicResult, TopicWord


class TestLDAConfig(unittest.TestCase):
    def test_default_config(self) -> None:
        config = LDAConfig()
        self.assertEqual(config.num_topics, 25)
        self.assertEqual(config.iterations, 500)

    def test_for_single_book(self) -> None:
        config = LDAConfig.for_single_book()
        self.assertEqual(config.num_topics, 25)
        self.assertEqual(config.iterations, 500)

    def test_lda_batch_size_is_the_public_config_name(self) -> None:
        config = LDAConfig(lda_batch_size=123)
        self.assertEqual(config.lda_batch_size, 123)

class TestTopicWord(unittest.TestCase):
    def test_creation(self) -> None:
        tw = TopicWord(word="测试", weight=0.5)
        self.assertEqual(tw.word, "测试")
        self.assertEqual(tw.weight, 0.5)

    def test_to_dict(self) -> None:
        tw = TopicWord(word="测试", weight=0.5)
        d = tw.to_dict()
        self.assertEqual(d["word"], "测试")
        self.assertEqual(d["weight"], 0.5)


class TestTopicResult(unittest.TestCase):
    def test_creation(self) -> None:
        result = TopicResult(topic_id=0, weight=0.8)
        self.assertEqual(result.topic_id, 0)
        self.assertEqual(result.weight, 0.8)
        self.assertIsNone(result.label)

    def test_to_dict(self) -> None:
        words = [TopicWord(word="词1", weight=0.3), TopicWord(word="词2", weight=0.2)]
        result = TopicResult(topic_id=1, weight=0.5, words=words, label="测试主题")
        d = result.to_dict()
        self.assertEqual(d["topic_id"], 1)
        self.assertEqual(d["weight"], 0.5)
        self.assertEqual(d["label"], "测试主题")
        self.assertEqual(len(d["words"]), 2)

class TestTopicModel(unittest.TestCase):
    def test_get_topic_words(self) -> None:
        mock_lda = MagicMock()
        mock_lda.show_topic.return_value = [("词1", 0.1), ("词2", 0.05)]
        mock_lda.num_topics = 5
        mock_dict = MagicMock()
        mock_corpus = MagicMock()

        model = TopicModel(
            num_topics=5,
            dictionary=mock_dict,
            lda_model=mock_lda,
            corpus=mock_corpus,
        )

        words = model.get_topic_words(0, top_n=2)
        self.assertEqual(len(words), 2)
        self.assertEqual(words[0].word, "词1")
        self.assertEqual(words[0].weight, 0.1)

    def test_get_topic_words_invalid_id(self) -> None:
        mock_lda = MagicMock()
        mock_lda.num_topics = 5
        model = TopicModel(
            num_topics=5,
            dictionary=MagicMock(),
            lda_model=mock_lda,
            corpus=MagicMock(),
        )
        words = model.get_topic_words(10)
        self.assertEqual(words, [])

    def test_infer_document_topics(self) -> None:
        mock_lda = MagicMock()
        mock_lda.get_document_topics.return_value = [(0, 0.6), (1, 0.3), (2, 0.1)]
        mock_lda.show_topic.return_value = [("词1", 0.1)]
        mock_lda.num_topics = 5
        mock_dict = MagicMock()
        mock_dict.doc2bow.return_value = [(0, 1), (1, 1)]

        model = TopicModel(
            num_topics=5,
            dictionary=mock_dict,
            lda_model=mock_lda,
            corpus=MagicMock(),
        )

        results = model.infer_document_topics(["测试"], top_n=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].topic_id, 0)
        self.assertEqual(results[0].weight, 0.6)

    def test_infer_document_topics_empty(self) -> None:
        mock_dict = MagicMock()
        mock_dict.doc2bow.return_value = []
        model = TopicModel(
            num_topics=5,
            dictionary=mock_dict,
            lda_model=MagicMock(),
            corpus=MagicMock(),
        )
        results = model.infer_document_topics([])
        self.assertEqual(results, [])

class TestLDATrainer(unittest.TestCase):
    def test_train_basic(self) -> None:
        tokenized_docs = [
            ["词1", "词2", "词3"],
            ["词2", "词3", "词4"],
            ["词1", "词4", "词5"],
        ]
        config = LDAConfig(num_topics=2, iterations=10, passes=1)
        trainer = LDATrainer(config)
        model = trainer.train(tokenized_docs, filter_extremes=False)
        self.assertEqual(model.num_topics, 2)
        self.assertIsNotNone(model.dictionary)
        self.assertIsNotNone(model.lda_model)

    @unittest.mock.patch("src.topic.lda_model.LdaModel")
    def test_gensim_adapter_receives_chunksize(self, lda_model: MagicMock) -> None:
        """2026-08-20 验证新配置名正确映射到 gensim 底层参数"""
        dictionary = MagicMock()
        dictionary.doc2bow.return_value = [(0, 1)]
        lda_model.return_value.num_topics = 2
        trainer = LDATrainer(LDAConfig(num_topics=2, iterations=1, passes=1, lda_batch_size=123))

        with unittest.mock.patch("src.topic.lda_model.Dictionary", return_value=dictionary):
            trainer.train([["词"]], filter_extremes=False)

        self.assertEqual(lda_model.call_args.kwargs["chunksize"], 123)


class TestHelperFunctions(unittest.TestCase):
    def test_get_topic_words(self) -> None:
        mock_lda = MagicMock()
        mock_lda.show_topic.return_value = [("词1", 0.1), ("词2", 0.05)]
        mock_lda.num_topics = 5
        model = TopicModel(
            num_topics=5,
            dictionary=MagicMock(),
            lda_model=mock_lda,
            corpus=MagicMock(),
        )
        words = get_topic_words(model, 0, top_n=2)
        self.assertEqual(len(words), 2)
        self.assertIn("word", words[0])

    def test_get_all_topic_words(self) -> None:
        mock_lda = MagicMock()
        mock_lda.show_topic.return_value = [("词1", 0.1)]
        mock_lda.num_topics = 2
        model = TopicModel(
            num_topics=2,
            dictionary=MagicMock(),
            lda_model=mock_lda,
            corpus=MagicMock(),
        )
        all_words = get_all_topic_words(model, top_n=1)
        self.assertEqual(len(all_words), 2)
        self.assertIn(0, all_words)
        self.assertIn(1, all_words)


if __name__ == "__main__":
    unittest.main()
