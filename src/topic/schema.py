from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: 段落主题推断状态（《分析能力扩展路线图》§5.9）
INFERENCE_COMPLETE = "complete"
INFERENCE_EMPTY_AFTER_PREPROCESS = "empty_after_preprocess"
INFERENCE_EMPTY_BOW = "empty_bow"
INFERENCE_FAILED = "failed"


@dataclass(frozen=True)
class ParagraphInferenceResult:
    """单个段落的完整主题推断结果。

    distribution 为完整 K 维 (topic_id, weight) 列表（仅 complete 状态非空），
    推断状态与 token 数进入 paragraph_topic_inference，分布进入 paragraph_topics。
    """

    inference_status: str
    inference_token_count: int
    distribution: tuple[tuple[int, float], ...] | None = None
    distribution_sum: float | None = None
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class TopicWord:
    word: str
    weight: float

    def to_dict(self) -> dict[str, Any]:
        return {"word": self.word, "weight": self.weight}


@dataclass(frozen=True)
class TopicResult:
    topic_id: int
    weight: float
    words: list[TopicWord] = field(default_factory=list)
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "weight": self.weight,
            "words": [w.to_dict() for w in self.words],
            "label": self.label,
        }


@dataclass
class TopicModel:
    num_topics: int
    dictionary: Any
    lda_model: Any
    corpus: Any
    labels: dict[int, str] = field(default_factory=dict)

    def get_topic_words(self, topic_id: int, top_n: int = 15) -> list[TopicWord]:
        if topic_id < 0 or topic_id >= self.num_topics:
            return []
        raw_words = self.lda_model.show_topic(topic_id, topn=top_n)
        return [TopicWord(word=w, weight=float(wt)) for w, wt in raw_words]

    def get_all_topics(self, top_n: int = 15) -> dict[int, list[TopicWord]]:
        result: dict[int, list[TopicWord]] = {}
        for topic_id in range(self.num_topics):
            result[topic_id] = self.get_topic_words(topic_id, top_n)
        return result

    def infer_document_topics(self, doc_tokens: list[str], top_n: int = 5) -> list[TopicResult]:
        bow = self.dictionary.doc2bow(doc_tokens)
        if not bow:
            return []
        topic_dist = self.lda_model.get_document_topics(bow, minimum_probability=0.0)
        sorted_topics = sorted(topic_dist, key=lambda x: x[1], reverse=True)[:top_n]
        results: list[TopicResult] = []
        for topic_id, weight in sorted_topics:
            words = self.get_topic_words(topic_id)
            label = self.labels.get(topic_id)
            results.append(TopicResult(topic_id=topic_id, weight=float(weight), words=words, label=label))
        return results

    def infer_full_distribution(self, doc_tokens: list[str]) -> ParagraphInferenceResult:
        """按完整 K 维分布推断段落主题（《分析能力扩展路线图》§5.9/§5.10）。

        top_n 只属于 API 展示裁剪，不进入持久化；本方法始终输出 0..K-1
        全覆盖的权重列表，缺省主题补零以保证段落权重和守恒。
        """
        bow = self.dictionary.doc2bow(doc_tokens)
        inference_token_count = sum(count for _, count in bow)
        if not bow:
            return ParagraphInferenceResult(
                inference_status=INFERENCE_EMPTY_BOW,
                inference_token_count=0,
                unavailable_reason="empty_bow: 预处理后有词元但词典映射后 BOW 为空",
            )
        raw_dist = self.lda_model.get_document_topics(bow, minimum_probability=0.0)
        weights: dict[int, float] = dict(raw_dist)
        distribution = tuple(
            (topic_id, float(weights.get(topic_id, 0.0))) for topic_id in range(self.num_topics)
        )
        distribution_sum = float(sum(weight for _, weight in distribution))
        return ParagraphInferenceResult(
            inference_status=INFERENCE_COMPLETE,
            inference_token_count=inference_token_count,
            distribution=distribution,
            distribution_sum=distribution_sum,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "num_topics": self.num_topics,
            "labels": dict(self.labels),
            "topics": {str(k): [w.to_dict() for w in v] for k, v in self.get_all_topics().items()},
        }
