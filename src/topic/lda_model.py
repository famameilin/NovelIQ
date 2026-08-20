from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gensim.corpora import Dictionary
from gensim.models import LdaModel
from loguru import logger

from src.config import settings

from .schema import TopicModel, TopicResult


@dataclass
class LDAConfig:
    num_topics: int | None = None
    passes: int | None = None
    iterations: int | None = None
    alpha: str | None = None
    eta: str | None = None
    random_state: int | None = None
    lda_batch_size: int | None = None
    minimum_probability: float | None = None

    def __post_init__(self) -> None:
        if self.num_topics is None:
            self.num_topics = settings.topic_model.num_topics
        if self.passes is None:
            self.passes = settings.topic_model.passes
        if self.iterations is None:
            self.iterations = settings.topic_model.iterations
        if self.alpha is None:
            self.alpha = settings.topic_model.lda.alpha
        if self.eta is None:
            self.eta = settings.topic_model.lda.eta
        if self.random_state is None:
            self.random_state = settings.topic_model.lda.random_state
        if self.lda_batch_size is None:
            self.lda_batch_size = settings.topic_model.lda.lda_batch_size
        if self.minimum_probability is None:
            self.minimum_probability = settings.topic_model.lda.minimum_probability

    @classmethod
    def for_single_book(cls) -> LDAConfig:
        return cls(
            num_topics=settings.topic_model.num_topics,
            passes=settings.topic_model.passes,
            iterations=settings.topic_model.iterations,
        )


class LDATrainer:
    def __init__(self, config: LDAConfig | None = None) -> None:
        self._config = config or LDAConfig.for_single_book()

    def train(
        self,
        tokenized_docs: list[list[str]],
        filter_extremes: bool = True,
        no_below: int | None = None,
        no_above: float | None = None,
    ) -> TopicModel:
        if no_below is None:
            no_below = settings.topic_model.lda.no_below
        if no_above is None:
            no_above = settings.topic_model.lda.no_above
        logger.info(
            "开始LDA训练: 主题数={}, 文档数={}, 迭代次数={}",
            self._config.num_topics,
            len(tokenized_docs),
            self._config.iterations,
        )
        dictionary = Dictionary(tokenized_docs)
        if filter_extremes:
            dictionary.filter_extremes(no_below=no_below, no_above=no_above)
            logger.debug(
                "词典过滤完成: 唯一词数={} (no_below={}, no_above={:.2f})",
                len(dictionary),
                no_below,
                no_above,
            )
        corpus = [dictionary.doc2bow(doc) for doc in tokenized_docs]
        logger.debug("创建语料库: 文档数={}", len(corpus))
        lda_model = LdaModel(
            corpus=corpus,
            id2word=dictionary,
            num_topics=self._config.num_topics,
            passes=self._config.passes,
            iterations=self._config.iterations,
            alpha=self._config.alpha,
            eta=self._config.eta,
            random_state=self._config.random_state,
            # gensim 的底层接口仍使用 chunksize，本模块配置契约使用 lda_batch_size
            chunksize=self._config.lda_batch_size,
            minimum_probability=self._config.minimum_probability,
        )
        logger.info("LDA训练完成")
        assert self._config.num_topics is not None
        return TopicModel(
            num_topics=self._config.num_topics,
            dictionary=dictionary,
            lda_model=lda_model,
            corpus=corpus,
        )

    def save_model(self, topic_model: TopicModel, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        topic_model.lda_model.save(str(output_dir / "lda_model"))
        topic_model.dictionary.save(str(output_dir / "dictionary"))
        if topic_model.labels:
            labels_path = output_dir / "labels.json"
            with open(labels_path, "w", encoding="utf-8") as f:
                json.dump({str(k): v for k, v in topic_model.labels.items()}, f, ensure_ascii=False, indent=2)
            logger.info("主题标签已保存: {}", labels_path)
        logger.info("LDA模型已保存: {}", output_dir)

    def load_model(self, input_dir: Path) -> TopicModel:
        lda_model = LdaModel.load(str(input_dir / "lda_model"))
        dictionary = Dictionary.load(str(input_dir / "dictionary"))
        labels: dict[int, str] = {}
        labels_path = input_dir / "labels.json"
        if labels_path.exists():
            with open(labels_path, encoding="utf-8") as f:
                labels = {int(k): v for k, v in json.load(f).items()}
            logger.info("主题标签已加载: {}", labels_path)
        logger.info("LDA模型已加载: {}", input_dir)
        return TopicModel(
            num_topics=lda_model.num_topics,
            dictionary=dictionary,
            lda_model=lda_model,
            corpus=None,
            labels=labels,
        )


def infer_document_topics(
    topic_model: TopicModel,
    doc_tokens: list[str],
    top_n: int = 5,
) -> list[TopicResult]:
    return topic_model.infer_document_topics(doc_tokens, top_n)


def get_topic_words(
    topic_model: TopicModel,
    topic_id: int,
    top_n: int = 15,
) -> list[dict[str, Any]]:
    words = topic_model.get_topic_words(topic_id, top_n)
    return [{"word": w.word, "weight": w.weight} for w in words]


def get_all_topic_words(
    topic_model: TopicModel,
    top_n: int = 15,
) -> dict[int, list[dict[str, Any]]]:
    all_topics = topic_model.get_all_topics(top_n)
    return {topic_id: [{"word": w.word, "weight": w.weight} for w in words] for topic_id, words in all_topics.items()}
