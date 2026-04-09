import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.cloud.client import NullCloudModelClient
from src.models.cloud.schema import CloudAnalysis
from src.topic.namer import (
    CachedTopicNamer,
    CloudTopicNamer,
    NullTopicNamer,
    TopicNamer,
    apply_topic_labels,
    create_topic_namer,
)
from src.topic.schema import TopicModel, TopicWord


class TestNullTopicNamer(unittest.TestCase):
    def test_name_topic(self) -> None:
        namer = NullTopicNamer()
        words = [TopicWord(word="词1", weight=0.5)]
        label = namer.name_topic(0, words)
        self.assertEqual(label, "主题1")

    def test_name_topic_different_id(self) -> None:
        namer = NullTopicNamer()
        label = namer.name_topic(5, [])
        self.assertEqual(label, "主题6")


class TestCloudTopicNamer(unittest.TestCase):
    def test_name_topic_success(self) -> None:
        mock_analysis = CloudAnalysis(
            novel_id=None,
            foreshadow_rate=None,
            arc_scores=[],
            narrative_type=None,
            topic_labels=["修仙"],
            diagnosis=None,
        )
        mock_client = MagicMock()
        mock_client.diagnose = AsyncMock(return_value=mock_analysis)

        namer = CloudTopicNamer(mock_client)
        words = [TopicWord(word="修炼", weight=0.1), TopicWord(word="境界", weight=0.05)]
        label = namer.name_topic(0, words)
        self.assertEqual(label, "修仙")

    def test_name_topic_empty_words(self) -> None:
        mock_client = MagicMock()
        namer = CloudTopicNamer(mock_client)
        label = namer.name_topic(0, [])
        self.assertEqual(label, "主题1")

    def test_name_topic_exception(self) -> None:
        mock_client = MagicMock()
        mock_client.diagnose = AsyncMock(side_effect=Exception("API error"))
        namer = CloudTopicNamer(mock_client)
        words = [TopicWord(word="词1", weight=0.5)]
        label = namer.name_topic(0, words)
        self.assertEqual(label, "主题1")

    def test_name_topic_caches_result(self) -> None:
        mock_analysis = CloudAnalysis(
            novel_id=None,
            foreshadow_rate=None,
            arc_scores=[],
            narrative_type=None,
            topic_labels=["测试"],
            diagnosis=None,
        )
        mock_client = MagicMock()
        mock_client.diagnose = AsyncMock(return_value=mock_analysis)

        namer = CloudTopicNamer(mock_client)
        words = [TopicWord(word="词1", weight=0.5)]
        namer.name_topic(0, words)
        namer.name_topic(0, words)
        mock_client.diagnose.assert_called_once()


class TestCachedTopicNamer(unittest.TestCase):
    def test_caches_result(self) -> None:
        inner = MagicMock(spec=TopicNamer)
        inner.name_topic.return_value = "测试主题"
        namer = CachedTopicNamer(inner)
        words = [TopicWord(word="词1", weight=0.5)]
        result1 = namer.name_topic(0, words)
        result2 = namer.name_topic(0, words)
        self.assertEqual(result1, "测试主题")
        self.assertEqual(result2, "测试主题")
        inner.name_topic.assert_called_once()

    def test_get_cache(self) -> None:
        inner = MagicMock(spec=TopicNamer)
        inner.name_topic.return_value = "测试主题"
        namer = CachedTopicNamer(inner)
        namer.name_topic(0, [])
        cache = namer.get_cache()
        self.assertIn(0, cache)
        self.assertEqual(cache[0], "测试主题")

    def test_load_cache(self) -> None:
        inner = MagicMock(spec=TopicNamer)
        namer = CachedTopicNamer(inner)
        namer.load_cache({0: "已有主题", 1: "另一个主题"})
        result = namer.name_topic(0, [])
        self.assertEqual(result, "已有主题")
        inner.name_topic.assert_not_called()


class TestCreateTopicNamer(unittest.TestCase):
    def test_creates_null_namer_when_no_client(self) -> None:
        namer = create_topic_namer(None)
        self.assertIsInstance(namer, NullTopicNamer)

    def test_creates_null_namer_when_null_client(self) -> None:
        namer = create_topic_namer(NullCloudModelClient())
        self.assertIsInstance(namer, NullTopicNamer)

    def test_creates_cached_namer_by_default(self) -> None:
        mock_client = MagicMock()
        namer = create_topic_namer(mock_client, use_cache=True)
        self.assertIsInstance(namer, CachedTopicNamer)

    def test_creates_uncached_namer(self) -> None:
        mock_client = MagicMock()
        namer = create_topic_namer(mock_client, use_cache=False)
        self.assertIsInstance(namer, CloudTopicNamer)


class TestApplyTopicLabels(unittest.TestCase):
    def test_apply_labels(self) -> None:
        mock_lda = MagicMock()
        mock_lda.num_topics = 3
        model = TopicModel(
            num_topics=3,
            dictionary=MagicMock(),
            lda_model=mock_lda,
            corpus=MagicMock(),
        )
        labels = {0: "主题A", 1: "主题B"}
        apply_topic_labels(model, labels)
        self.assertEqual(model.labels[0], "主题A")
        self.assertEqual(model.labels[1], "主题B")


if __name__ == "__main__":
    unittest.main()
