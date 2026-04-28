"""
主题查询组装器

说明: 承载 topics 相关查询组装逻辑
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from src.api.models.responses import TopicInfo
from src.storage.repositories import ChunkRepository

from .common import _normalize_name_list


def _fetch_topics(run_id: str, chunk_repo: ChunkRepository, alias_map: dict[str, str] | None = None) -> list:
    """获取主题数据"""
    rows = chunk_repo.fetch_chunk_topics_agg(run_id)

    model_dir = Path("models") / "topic" / run_id
    topic_words_map: dict[int, list[str]] = {}
    topic_labels_map: dict[int, str] = {}

    if model_dir.exists():
        try:
            from src.topic import LDAConfig, LDATrainer

            trainer = LDATrainer(LDAConfig())
            topic_model = trainer.load_model(model_dir)
            for topic_id in range(topic_model.num_topics):
                topic_words = topic_model.get_topic_words(topic_id, top_n=10)
                topic_words_map[topic_id] = [word.word for word in topic_words]
                if topic_model.labels:
                    label = topic_model.labels.get(topic_id)
                    if label:
                        topic_labels_map[topic_id] = label
        except (FileNotFoundError, ImportError, OSError, ValueError) as exc:
            logger.warning(f"Failed to load topic model: {exc}")

    result: list[TopicInfo] = []
    for row in rows:
        topic_id = row.topic_id
        words: list[str] = topic_words_map.get(topic_id, [])
        words = _normalize_name_list(words, alias_map) or []
        label = topic_labels_map.get(topic_id)
        if words:
            result.append(TopicInfo(topic_id=topic_id, words=words, weight=row.total_weight, label=label))

    if result:
        total_weight = sum(item.weight for item in result)
        if total_weight > 0:
            result = [
                TopicInfo(
                    topic_id=item.topic_id,
                    words=item.words,
                    weight=round(item.weight / total_weight, 6),
                    label=item.label,
                )
                for item in result
            ]

    return result
