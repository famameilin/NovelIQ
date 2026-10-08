"""所属领域的字段契约与结果处理"""

from __future__ import annotations

from math import isfinite
from pathlib import Path
from typing import Any, Protocol, cast

from loguru import logger

from src.config.paths import resolve_model_dir


class _TopicAggregationRow(Protocol):
    topic_id: object
    weighted_total: Any


def validate_topic_aggregation_row(row: object) -> tuple[int, float]:
    """2026-08-20 校验主题聚合行并返回语义化字段"""
    typed_row = cast(_TopicAggregationRow, row)
    try:
        raw_topic_id = typed_row.topic_id
        raw_weighted_total = typed_row.weighted_total
    except AttributeError as exc:
        raise RuntimeError("paragraph_topics 聚合结果缺少 topic_id 或 weighted_total 字段") from exc

    if isinstance(raw_topic_id, bool) or not isinstance(raw_topic_id, int):
        raise RuntimeError(f"paragraph_topics 聚合结果 topic_id 类型错误: {type(raw_topic_id).__name__}")
    try:
        weighted_total = float(raw_weighted_total)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"paragraph_topics 聚合结果 weighted_total 类型错误: {raw_weighted_total!r}") from exc
    if not isfinite(weighted_total) or weighted_total < 0:
        raise RuntimeError(f"paragraph_topics 聚合结果 weighted_total 必须是非负有限数: {weighted_total!r}")
    return raw_topic_id, weighted_total


def load_topic_artifact(
    model_dir: Path,
) -> tuple[dict[int, list[str]], dict[int, str], str | None]:
    """加载主题词与标签映射

    2026-09-05 A6：artifact 缺失/加载失败不再静默——第三返回值给出显式原因，
    供导出层把 topics 缺失写进 missing_fields（报告附录 B 可核查）。
    """
    topic_words_map: dict[int, list[str]] = {}
    topic_labels_map: dict[int, str] = {}

    if not model_dir.exists():
        return topic_words_map, topic_labels_map, f"topic_model_artifact_missing: {model_dir.as_posix()}"
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
        return topic_words_map, topic_labels_map, f"topic_model_load_failed: {exc}"
    return topic_words_map, topic_labels_map, None


def describe_topics_unavailability(run_id: str) -> str | None:
    """2026-09-05 A6 用于在主题聚合为空时探测显式原因（无 artifact 时不再静默消失）"""
    _, _, reason = load_topic_words(run_id)
    return reason


def load_topic_words(run_id: str) -> tuple[dict[int, list[str]], dict[int, str], str | None]:
    """按配置解析模型产物位置，复用唯一的主题产物读取实现"""
    return load_topic_artifact(resolve_model_dir(run_id))
