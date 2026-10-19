"主题链路（ LDA 构建事实 /  inference /  lda_paragraph_topics）"

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import Table, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from src.config.paths import resolve_model_dir, resolve_project_root
from src.storage.models import (
    Chapter,
    Paragraph,
    ParagraphMetric,
    ParagraphTopic,
    Run,
)
from src.storage.records.topic import TopicModelRunContract
from src.storage.repositories.metric_inputs import (
    global_start_char_projection,
    net_density_projection,
)

#: 推断状态封闭词表值（完整取值与说明见 src.topic.schema）
INFERENCE_STATUS_COMPLETE = "complete"

#: 需要显式清空的段落推断列（重跑先清后插）
_INFERENCE_COLUMNS = (
    "inference_token_count",
    "inference_status",
    "inference_error_text",
    "inference_created_at",
)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def project_topic_artifact_key(run_id: str) -> str:
    "artifact_key 读投影：按当前 resolve_model_dir 与项目根规则解析"
    return str(resolve_model_dir(run_id).relative_to(resolve_project_root()).as_posix())


def _load_topic_artifact(run_id: str):
    "读取模型与词典并核对二者的词元编号"
    from gensim.corpora import Dictionary
    from gensim.models import LdaModel

    directory = resolve_model_dir(run_id)
    model = LdaModel.load(str(directory / "lda_model"))
    dictionary = Dictionary.load(str(directory / "dictionary"))
    if (
        not dictionary
        or len(dictionary) != len(model.id2word)
        or any(model.id2word[index] != token for index, token in dictionary.items())
    ):
        raise ValueError("LDA 模型与词典产物不一致")
    return model


def insert_topic_model_run(session: Session, run_id: str, *, num_topics: int, **parameters: Any) -> None:
    "保存并验证实际 LDA 产物后标记完成"
    model = _load_topic_artifact(run_id)
    if model.num_topics != num_topics or not model.id2word:
        raise ValueError("LDA 产物主题数或词典校验失败")
    session.execute(update(Run).where(Run.id == run_id).values(lda_completed=True))


def fetch_complete_inference_count(session: Session, run_id: str) -> int:
    "inference_paragraph_count 读投影：正式推断状态为 complete 的段落数"
    count = session.execute(
        select(func.count())
        .select_from(ParagraphMetric)
        .where(
            ParagraphMetric.run_id == run_id,
            ParagraphMetric.inference_status == INFERENCE_STATUS_COMPLETE,
        )
    ).scalar()
    return int(count or 0)


def fetch_topic_model_run(session: Session, run_id: str) -> TopicModelRunContract | None:
    "从实际产物读取主题模型属性"
    if not session.scalar(select(Run.lda_completed).where(Run.id == run_id)):
        return None
    model = _load_topic_artifact(run_id)
    return TopicModelRunContract(
        run_id=run_id,
        num_topics=model.num_topics,
        dictionary_size=len(model.id2word),
        inference_paragraph_count=fetch_complete_inference_count(session, run_id),
        artifact_key=project_topic_artifact_key(run_id),
    )


def insert_paragraph_topic_inferences(
    session: Session,
    run_id: str,
    rows: Sequence[tuple[int, int, int, str, str | None, float | None]],
) -> int:
    "全量 upsert 写入 run 的段落推断事实（paragraph_metrics.inference_* 列）"
    inference_rows = [
        {
            "run_id": run_id,
            "paragraph_id": paragraph_id,
            "inference_token_count": inference_token_count,
            "inference_status": inference_status,
            "inference_error_text": None,
            "inference_created_at": _utcnow(),
        }
        for (
            paragraph_id,
            _source_token_count,
            inference_token_count,
            inference_status,
            _unavailable_reason,
            _distribution_sum,
        ) in rows
    ]
    if not inference_rows:
        return 0
    statement = pg_insert(ParagraphMetric).values(inference_rows)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["run_id", "paragraph_id"],
            set_={
                "inference_token_count": statement.excluded.inference_token_count,
                "inference_status": statement.excluded.inference_status,
                "inference_error_text": statement.excluded.inference_error_text,
                "inference_created_at": statement.excluded.inference_created_at,
            },
        )
    )
    return len(inference_rows)


def clear_paragraph_topic_inferences(session: Session, run_id: str) -> None:
    "清空 run 的段落推断状态列（纯清理场景专用）"
    session.execute(
        update(ParagraphMetric).where(ParagraphMetric.run_id == run_id).values(**dict.fromkeys(_INFERENCE_COLUMNS))
    )


def fetch_topic_inference_total(session: Session, run_id: str) -> int | None:
    "全书主题推断分母：所有段落的 inference_token_count 之和"
    return session.execute(
        select(func.sum(ParagraphMetric.inference_token_count)).where(ParagraphMetric.run_id == run_id)
    ).scalar_one_or_none()


def fetch_chapter_inference_totals(session: Session, run_id: str) -> Sequence[Row]:
    "按章节返回推断 token 分母（每段一格， 章节聚合分母）"
    stmt = (
        select(
            Chapter.chapter_id,
            Chapter.sequence,
            Chapter.title,
            func.sum(ParagraphMetric.inference_token_count).label("token_total"),
        )
        .select_from(Chapter)
        .join(Paragraph, (Paragraph.run_id == Chapter.run_id) & (Paragraph.chapter_id == Chapter.chapter_id))
        .join(
            ParagraphMetric,
            (ParagraphMetric.run_id == Paragraph.run_id) & (ParagraphMetric.paragraph_id == Paragraph.paragraph_id),
        )
        .where(Paragraph.run_id == run_id)
        .group_by(Chapter.chapter_id, Chapter.sequence, Chapter.title)
        .order_by(Chapter.sequence)
    )
    return session.execute(stmt).all()


def fetch_topic_emotion_aggregates(session: Session, run_id: str) -> Sequence[Row]:
    "主题-情感分子分母：净密度为 NULL 的段落在 SQL 层同时排除"
    net_density = net_density_projection()
    stmt = (
        select(
            ParagraphTopic.topic_id,
            func.sum(ParagraphTopic.topic_weight * ParagraphMetric.inference_token_count * net_density).label(
                "emotion_total"
            ),
            func.sum(ParagraphTopic.topic_weight * ParagraphMetric.inference_token_count).label("weighted_token_total"),
        )
        .select_from(ParagraphTopic)
        .join(
            ParagraphMetric,
            (ParagraphMetric.run_id == ParagraphTopic.run_id)
            & (ParagraphMetric.paragraph_id == ParagraphTopic.paragraph_id),
        )
        .where(
            ParagraphTopic.run_id == run_id,
            ParagraphMetric.token_count > 0,
        )
        .group_by(ParagraphTopic.topic_id)
        .order_by(ParagraphTopic.topic_id)
    )
    return session.execute(stmt).all()


def insert_paragraph_topics(
    session: Session,
    run_id: str,
    rows: Sequence[tuple[int, int, float]],
) -> int:
    '先清后插写入 run 的段落主题行（同 run 重跑语义是"重新计算"）'
    from math import isclose, isfinite

    model = _load_topic_artifact(run_id)
    distributions: dict[int, dict[int, float]] = {}
    for paragraph_id, topic_id, weight in rows:
        distribution = distributions.setdefault(paragraph_id, {})
        if topic_id in distribution or not isfinite(weight) or weight < 0:
            raise ValueError("段落主题概率无效或重复")
        distribution[topic_id] = weight
    for distribution in distributions.values():
        if set(distribution) != set(range(model.num_topics)) or not isclose(
            sum(distribution.values()), 1, abs_tol=1e-5
        ):
            raise ValueError("段落主题分布与实际模型不一致")
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
    # __table__ 静态类型是 FromClause，运行期是映射的真实 Table（行插入需要它）
    session.execute(cast(Table, ParagraphTopic.__table__).insert(), topic_rows)
    return len(topic_rows)


def clear_paragraph_topics(session: Session, run_id: str) -> None:
    "清空 run 的段落主题行"
    session.execute(delete(ParagraphTopic).where(ParagraphTopic.run_id == run_id))


def fetch_paragraph_topics_agg(session: Session, run_id: str) -> Sequence[Row]:
    "全书主题分子：按主题返回 token 加权和"
    stmt = (
        select(
            ParagraphTopic.topic_id,
            func.sum(ParagraphTopic.topic_weight * ParagraphMetric.inference_token_count).label("weighted_total"),
        )
        .select_from(ParagraphTopic)
        .join(
            ParagraphMetric,
            (ParagraphMetric.run_id == ParagraphTopic.run_id)
            & (ParagraphMetric.paragraph_id == ParagraphTopic.paragraph_id),
        )
        .where(ParagraphTopic.run_id == run_id)
        .group_by(ParagraphTopic.topic_id)
    )
    return session.execute(stmt).all()


def fetch_chapter_topic_aggregates(session: Session, run_id: str) -> Sequence[Row]:
    "章节主题分子：按章节返回主题 token 加权和"
    stmt = (
        select(
            Chapter.chapter_id,
            Chapter.sequence,
            Chapter.title,
            ParagraphTopic.topic_id,
            func.sum(ParagraphTopic.topic_weight * ParagraphMetric.inference_token_count).label("weighted_total"),
        )
        .select_from(Chapter)
        .join(Paragraph, (Paragraph.run_id == Chapter.run_id) & (Paragraph.chapter_id == Chapter.chapter_id))
        .join(
            ParagraphMetric,
            (ParagraphMetric.run_id == Paragraph.run_id) & (ParagraphMetric.paragraph_id == Paragraph.paragraph_id),
        )
        .join(
            ParagraphTopic,
            (ParagraphTopic.run_id == Paragraph.run_id) & (ParagraphTopic.paragraph_id == Paragraph.paragraph_id),
        )
        .where(Paragraph.run_id == run_id)
        .group_by(Chapter.chapter_id, Chapter.sequence, Chapter.title, ParagraphTopic.topic_id)
        .order_by(Chapter.sequence, ParagraphTopic.topic_id)
    )
    return session.execute(stmt).all()


def fetch_paragraph_topic_rows(session: Session, run_id: str) -> Sequence[Row]:
    "段落主题序列数据：段落真实字符位置、章节序列与"
    global_start_char = global_start_char_projection()
    stmt = (
        select(
            Paragraph.paragraph_id,
            Paragraph.chapter_id,
            Chapter.sequence,
            global_start_char.label("global_start_char"),
            ParagraphMetric.inference_token_count,
            ParagraphTopic.topic_id,
            ParagraphTopic.topic_weight,
        )
        .select_from(Paragraph)
        .join(Chapter, (Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Paragraph.chapter_id))
        .join(
            ParagraphMetric,
            (ParagraphMetric.run_id == Paragraph.run_id) & (ParagraphMetric.paragraph_id == Paragraph.paragraph_id),
        )
        .join(
            ParagraphTopic,
            (ParagraphTopic.run_id == Paragraph.run_id) & (ParagraphTopic.paragraph_id == Paragraph.paragraph_id),
        )
        .where(Paragraph.run_id == run_id)
        .order_by(global_start_char, ParagraphTopic.topic_id)
    )
    return session.execute(stmt).all()
