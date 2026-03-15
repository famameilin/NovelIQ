from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from loguru import logger

from src.models.cloud.client import CloudModelClient, NullCloudModelClient

from .schema import TopicModel, TopicWord


class TopicNamer(ABC):
    @abstractmethod
    def name_topic(self, topic_id: int, words: List[TopicWord]) -> str:
        pass

    def name_all_topics(self, topic_model: TopicModel, top_n: int = 15) -> Dict[int, str]:
        labels: Dict[int, str] = {}
        for topic_id in range(topic_model.num_topics):
            words = topic_model.get_topic_words(topic_id, top_n)
            labels[topic_id] = self.name_topic(topic_id, words)
        return labels


class NullTopicNamer(TopicNamer):
    def name_topic(self, topic_id: int, words: List[TopicWord]) -> str:
        return f"主题{topic_id + 1}"


class CloudTopicNamer(TopicNamer):
    def __init__(self, cloud_client: CloudModelClient) -> None:
        self._client = cloud_client
        self._cache: Dict[int, str] = {}

    def name_topic(self, topic_id: int, words: List[TopicWord]) -> str:
        if topic_id in self._cache:
            return self._cache[topic_id]
        if not words:
            return f"主题{topic_id + 1}"
        word_list = [f"{w.word}({w.weight:.4f})" for w in words[:10]]
        word_str = "、".join(word_list)
        prompt = self._build_prompt(word_str)
        try:
            label = self._call_cloud(prompt)
            if not label or len(label) > 20:
                label = f"主题{topic_id + 1}"
            self._cache[topic_id] = label
            return label
        except Exception as e:
            logger.warning("主题命名失败: topic_id={}, error={}", topic_id, e)
            return f"主题{topic_id + 1}"

    def _build_prompt(self, word_str: str) -> str:
        return (
            f"以下是一组从网络小说文本中提取的主题关键词及其权重：\n{word_str}\n\n"
            "请用一个简洁的中文短语（2-6个字）概括这些关键词所代表的主题。"
            "只输出主题名称，不要输出其他内容。"
        )

    def _call_cloud(self, prompt: str) -> str:
        payload = {"messages": [{"role": "user", "content": prompt}]}
        analysis = self._client.diagnose(payload)
        if analysis.topic_labels:
            return analysis.topic_labels[0]
        return ""


class CachedTopicNamer(TopicNamer):
    def __init__(self, inner: TopicNamer, cache: Dict[int, str] | None = None) -> None:
        self._inner = inner
        self._cache = cache if cache is not None else {}

    def name_topic(self, topic_id: int, words: List[TopicWord]) -> str:
        if topic_id in self._cache:
            logger.debug("缓存命中: topic_id={}", topic_id)
            return self._cache[topic_id]
        label = self._inner.name_topic(topic_id, words)
        self._cache[topic_id] = label
        return label

    def get_cache(self) -> Dict[int, str]:
        return self._cache.copy()

    def load_cache(self, cache: Dict[int, str]) -> None:
        self._cache.update(cache)


def create_topic_namer(
    cloud_client: CloudModelClient | None = None,
    use_cache: bool = True,
) -> TopicNamer:
    if cloud_client is None or isinstance(cloud_client, NullCloudModelClient):
        return NullTopicNamer()
    namer: TopicNamer = CloudTopicNamer(cloud_client)
    if use_cache:
        namer = CachedTopicNamer(namer)
    return namer


def apply_topic_labels(topic_model: TopicModel, labels: Dict[int, str]) -> None:
    topic_model.labels.update(labels)
