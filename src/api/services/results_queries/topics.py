"""
主题查询组装器

说明: 承载 topics 相关查询组装逻辑

Paragraph 粒度主题结果使用 paragraph_topics 的原始 token 加权聚合
（fetch_paragraph_topics_agg），归一化使用 weighted_total
"""

from __future__ import annotations

from math import isfinite
from typing import Any, Protocol, cast

from loguru import logger

from src.api.models.responses import TopicInfo
from src.storage.path_resolver import resolve_model_dir
from src.storage.repositories import ParagraphRepository


class _TopicAggregationRow(Protocol):
    topic_id: object
    weighted_total: Any


def _validate_agg_row(row: object) -> tuple[int, float]:
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


def _load_topic_words(
    run_id: str,
) -> tuple[dict[int, list[str]], dict[int, str], str | None]:
    """加载主题词与标签映射

    2026-09-05 A6：artifact 缺失/加载失败不再静默——第三返回值给出显式原因，
    供导出层把 topics 缺失写进 missing_fields（报告附录 B 可核查）。
    """
    model_dir = resolve_model_dir(run_id)
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
    _, _, reason = _load_topic_words(run_id)
    return reason


def _fetch_topics(run_id: str, paragraph_repo: ParagraphRepository) -> list:
    """获取主题数据（段落 token 加权聚合，weighted_total 归一化）"""
    rows = paragraph_repo.fetch_paragraph_topics_agg(run_id)
    topic_words_map, topic_labels_map, _reason = _load_topic_words(run_id)

    result: list[TopicInfo] = []
    for row in rows:
        topic_id, weighted_total = _validate_agg_row(row)
        words: list[str] = topic_words_map.get(topic_id, [])
        label = topic_labels_map.get(topic_id)
        if words:
            result.append(TopicInfo(topic_id=topic_id, words=words, weight=weighted_total, label=label))

    if result:
        book_total = paragraph_repo.fetch_topic_inference_total(run_id)
        if book_total:
            # §5.11 新口径：分母为全书所有段落推断 token 和（每段一行，不因 K 行放大）
            result = [
                TopicInfo(
                    topic_id=item.topic_id,
                    words=item.words,
                    weight=round(item.weight / book_total, 6),
                    label=item.label,
                )
                for item in result
            ]
        else:
            # 兼容旧 Top-5 运行（无 inference 表行）：按主题加权和归一
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
