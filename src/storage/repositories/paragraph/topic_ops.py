"""
主题链路（§5.8 topic_model_runs / §5.9 inference / §5.10 paragraph_topics）

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分——从 paragraph_repository.py 提取主题模型契约、
段落推断状态与主题-情感/章节/序列聚合逻辑
说明: 纯结构搬移，不改 SQL 与聚合口径；topic_model_runs 保存模型契约、
paragraph_topic_inference 每段一行保存推断状态与 token 分母、
paragraph_topics 只保存完整 K 维主题权重（分母不在此表重复保存）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Mapper, Session

from src.storage.models import (
    Chapter,
    Paragraph,
    ParagraphCurve,
    ParagraphTopic,
    ParagraphTopicInference,
    TopicModelRun,
)


def insert_topic_model_run(
    session: Session,
    run_id: str,
    *,
    model_key: str,
    library_version: str,
    pipeline_version: str,
    num_topics: int,
    parameters: dict[str, Any],
    dictionary_size: int,
    training_document_count: int,
    inference_paragraph_count: int,
    artifact_key: str,
) -> None:
    """先清后插写入 run 的主题模型契约（同 run 重跑语义是"重新计算"）"""
    session.execute(delete(TopicModelRun).where(TopicModelRun.run_id == run_id))
    session.execute(
        insert(TopicModelRun),
        {
            "run_id": run_id,
            "model_key": model_key,
            "library_version": library_version,
            "pipeline_version": pipeline_version,
            "num_topics": num_topics,
            "parameters": parameters,
            "dictionary_size": dictionary_size,
            "training_document_count": training_document_count,
            "inference_paragraph_count": inference_paragraph_count,
            "artifact_key": artifact_key,
        },
    )


def fetch_topic_model_run(session: Session, run_id: str) -> TopicModelRun | None:
    """读取 run 的主题模型契约行"""
    statement = select(TopicModelRun).where(TopicModelRun.run_id == run_id)
    return session.execute(statement).scalar_one_or_none()


def insert_paragraph_topic_inferences(
    session: Session,
    run_id: str,
    rows: Sequence[tuple[int, int, int, str, str | None, float | None]],
) -> int:
    """
    先清后插写入 run 的段落推断状态（每段一行）

    rows: (paragraph_id, source_token_count, inference_token_count,
           inference_status, unavailable_reason, distribution_sum)

    """
    inference_rows = [
        {
            "run_id": run_id,
            "paragraph_id": paragraph_id,
            "source_token_count": source_token_count,
            "inference_token_count": inference_token_count,
            "inference_status": inference_status,
            "unavailable_reason": unavailable_reason,
            "distribution_sum": distribution_sum,
        }
        for (
            paragraph_id,
            source_token_count,
            inference_token_count,
            inference_status,
            unavailable_reason,
            distribution_sum,
        ) in rows
    ]
    if not inference_rows:
        return 0
    session.execute(
        delete(ParagraphTopicInference).where(ParagraphTopicInference.run_id == run_id)
    )
    session.bulk_insert_mappings(cast(Mapper[Any], ParagraphTopicInference), inference_rows)
    return len(inference_rows)


def clear_paragraph_topic_inferences(session: Session, run_id: str) -> None:
    """清空 run 的段落推断状态行"""
    session.execute(delete(ParagraphTopicInference).where(ParagraphTopicInference.run_id == run_id))


def fetch_topic_inference_total(session: Session, run_id: str) -> int | None:
    """全书主题推断分母：所有段落（每段一行）的 inference_token_count 之和"""
    return session.execute(
        select(func.sum(ParagraphTopicInference.inference_token_count)).where(
            ParagraphTopicInference.run_id == run_id
        )
    ).scalar_one_or_none()


def fetch_chapter_inference_totals(session: Session, run_id: str) -> Sequence[Row]:
    """按章节返回推断 token 分母（每段一行，§5.11 章节聚合分母）"""
    stmt = (
        select(
            Chapter.chapter_id,
            Chapter.sequence,
            Chapter.title,
            func.sum(ParagraphTopicInference.inference_token_count).label("token_total"),
        )
        .select_from(Chapter)
        .join(Paragraph, (Paragraph.run_id == Chapter.run_id) & (Paragraph.chapter_id == Chapter.chapter_id))
        .join(
            ParagraphTopicInference,
            (ParagraphTopicInference.run_id == Paragraph.run_id)
            & (ParagraphTopicInference.paragraph_id == Paragraph.paragraph_id),
        )
        .where(Paragraph.run_id == run_id)
        .group_by(Chapter.chapter_id, Chapter.sequence, Chapter.title)
        .order_by(Chapter.sequence)
    )
    return session.execute(stmt).all()


def fetch_topic_emotion_aggregates(session: Session, run_id: str) -> Sequence[Row]:
    """主题-情感分子分母（§5.11）：net_density 空值段落在 SQL 层同时排除"""
    stmt = (
        select(
            ParagraphTopic.topic_id,
            func.sum(
                ParagraphTopic.topic_weight
                * ParagraphTopicInference.inference_token_count
                * ParagraphCurve.net_density
            ).label("emotion_total"),
            func.sum(ParagraphTopic.topic_weight * ParagraphTopicInference.inference_token_count).label(
                "weighted_token_total"
            ),
        )
        .join(
            ParagraphTopicInference,
            (ParagraphTopicInference.run_id == ParagraphTopic.run_id)
            & (ParagraphTopicInference.paragraph_id == ParagraphTopic.paragraph_id),
        )
        .join(
            ParagraphCurve,
            (ParagraphCurve.run_id == ParagraphTopic.run_id)
            & (ParagraphCurve.paragraph_id == ParagraphTopic.paragraph_id),
        )
        .where(ParagraphTopic.run_id == run_id, ParagraphCurve.net_density.is_not(None))
        .group_by(ParagraphTopic.topic_id)
        .order_by(ParagraphTopic.topic_id)
    )
    return session.execute(stmt).all()


def insert_paragraph_topics(
    session: Session,
    run_id: str,
    rows: Sequence[tuple[int, int, float]],
) -> int:
    """
    先清后插写入 run 的段落主题行（同 run 重跑语义是"重新计算"）

    rows: (paragraph_id, topic_id, topic_weight)；完整 K 维分布由调用方保证，
    token 分母不在此表重复保存（§5.10）

    """
    topic_rows = [
        {
            "run_id": run_id,
            "paragraph_id": paragraph_id,
            "topic_id": topic_id,
            "topic_weight": topic_weight,
        }
        for paragraph_id, topic_id, topic_weight in rows
    ]
    if not topic_rows:
        return 0
    session.execute(delete(ParagraphTopic).where(ParagraphTopic.run_id == run_id))
    session.bulk_insert_mappings(cast(Mapper[Any], ParagraphTopic), topic_rows)
    return len(topic_rows)


def clear_paragraph_topics(session: Session, run_id: str) -> None:
    """清空 run 的段落主题行"""
    session.execute(delete(ParagraphTopic).where(ParagraphTopic.run_id == run_id))


def fetch_paragraph_topics_agg(session: Session, run_id: str) -> Sequence[Row]:
    """
    全书主题分子：按主题返回 token 加权和（§5.11）

    分母为全书所有段落的 inference_token_count 之和（每段一行），
    由 fetch_topic_inference_total 提供；归一化在调用方完成。
    禁止对段落等权求和。
    """
    stmt = (
        select(
            ParagraphTopic.topic_id,
            func.sum(ParagraphTopic.topic_weight * ParagraphTopicInference.inference_token_count).label(
                "weighted_total"
            ),
        )
        .join(
            ParagraphTopicInference,
            (ParagraphTopicInference.run_id == ParagraphTopic.run_id)
            & (ParagraphTopicInference.paragraph_id == ParagraphTopic.paragraph_id),
        )
        .where(ParagraphTopic.run_id == run_id)
        .group_by(ParagraphTopic.topic_id)
    )
    return session.execute(stmt).all()


def fetch_chapter_topic_aggregates(session: Session, run_id: str) -> Sequence[Row]:
    """
    章节主题分子：按章节返回主题 token 加权和（§5.11）

    章节边界用 paragraphs.chapter_id 关联 chapters 并按 chapters.sequence
    排序，不使用段落列表下标推断章节；分母与归一化在调用方完成。

    """
    stmt = (
        select(
            Chapter.chapter_id,
            Chapter.sequence,
            Chapter.title,
            ParagraphTopic.topic_id,
            func.sum(ParagraphTopic.topic_weight * ParagraphTopicInference.inference_token_count).label(
                "weighted_total"
            ),
        )
        .select_from(Chapter)
        .join(Paragraph, (Paragraph.run_id == Chapter.run_id) & (Paragraph.chapter_id == Chapter.chapter_id))
        .join(
            ParagraphTopicInference,
            (ParagraphTopicInference.run_id == Paragraph.run_id)
            & (ParagraphTopicInference.paragraph_id == Paragraph.paragraph_id),
        )
        .join(
            ParagraphTopic,
            (ParagraphTopic.run_id == Paragraph.run_id)
            & (ParagraphTopic.paragraph_id == Paragraph.paragraph_id),
        )
        .where(Paragraph.run_id == run_id)
        .group_by(Chapter.chapter_id, Chapter.sequence, Chapter.title, ParagraphTopic.topic_id)
        .order_by(Chapter.sequence, ParagraphTopic.topic_id)
    )
    return session.execute(stmt).all()


def fetch_paragraph_topic_rows(session: Session, run_id: str) -> Sequence[Row]:
    """
    段落主题序列数据（§5.11）：段落真实字符位置、章节序列与
    推断 token 数齐备

    返回: (paragraph_id, chapter_id, chapter_sequence, global_start_char,
           inference_token_count, topic_id, topic_weight)
    """
    stmt = (
        select(
            Paragraph.paragraph_id,
            Paragraph.chapter_id,
            Chapter.sequence,
            Paragraph.global_start_char,
            ParagraphTopicInference.inference_token_count,
            ParagraphTopic.topic_id,
            ParagraphTopic.topic_weight,
        )
        .join(
            ParagraphTopicInference,
            (ParagraphTopicInference.run_id == Paragraph.run_id)
            & (ParagraphTopicInference.paragraph_id == Paragraph.paragraph_id),
        )
        .join(
            ParagraphTopic,
            (ParagraphTopic.run_id == Paragraph.run_id)
            & (ParagraphTopic.paragraph_id == Paragraph.paragraph_id),
        )
        .join(Chapter, (Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Paragraph.chapter_id))
        .where(Paragraph.run_id == run_id)
        .order_by(Paragraph.global_start_char, ParagraphTopic.topic_id)
    )
    return session.execute(stmt).all()
