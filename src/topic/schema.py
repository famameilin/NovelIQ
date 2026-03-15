from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class TopicWord:
    word: str
    weight: float

    def to_dict(self) -> Dict[str, Any]:
        return {"word": self.word, "weight": self.weight}


@dataclass(frozen=True)
class TopicResult:
    topic_id: int
    weight: float
    words: List[TopicWord] = field(default_factory=list)
    label: str | None = None

    def to_dict(self) -> Dict[str, Any]:
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
    labels: Dict[int, str] = field(default_factory=dict)

    def get_topic_words(self, topic_id: int, top_n: int = 15) -> List[TopicWord]:
        if topic_id < 0 or topic_id >= self.num_topics:
            return []
        raw_words = self.lda_model.show_topic(topic_id, topn=top_n)
        return [TopicWord(word=w, weight=float(wt)) for w, wt in raw_words]

    def get_all_topics(self, top_n: int = 15) -> Dict[int, List[TopicWord]]:
        result: Dict[int, List[TopicWord]] = {}
        for topic_id in range(self.num_topics):
            result[topic_id] = self.get_topic_words(topic_id, top_n)
        return result

    def infer_document_topics(self, doc_tokens: List[str], top_n: int = 5) -> List[TopicResult]:
        bow = self.dictionary.doc2bow(doc_tokens)
        if not bow:
            return []
        topic_dist = self.lda_model.get_document_topics(bow, minimum_probability=0.0)
        sorted_topics = sorted(topic_dist, key=lambda x: x[1], reverse=True)[:top_n]
        results: List[TopicResult] = []
        for topic_id, weight in sorted_topics:
            words = self.get_topic_words(topic_id)
            label = self.labels.get(topic_id)
            results.append(TopicResult(topic_id=topic_id, weight=float(weight), words=words, label=label))
        return results

    def to_dict(self) -> Dict[str, Any]:
        return {
            "num_topics": self.num_topics,
            "labels": dict(self.labels),
            "topics": {str(k): [w.to_dict() for w in v] for k, v in self.get_all_topics().items()},
        }
