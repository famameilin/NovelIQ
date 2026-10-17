"""
主题链路（§5.8 LDA 构建事实 / §5.9 inference / §5.10 paragraph_topics）

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分——从 paragraph_repository.py 提取主题模型契约、
段落推断状态与主题-情感/章节/序列聚合逻辑
说明: 纯结构搬移，不改 SQL 与聚合口径；paragraph_topics 只保存完整 K 维
主题权重（分母不在此表重复保存）。

2026-10-16 全库 3NF 改造（35 表冻结结构）：
- LDA 实际构建列上提到 analysis_runs 的 lda_* 具名列（含 library/pipeline
  版本、K、词典规模、训练文档数、标量超参与构建时间）；model_key 按固定实现
  合同投影、artifact_key 按 resolve_model_dir 投影、inference_paragraph_count
  由正式推断状态聚合，三者不再落列
- 段落推断状态写 paragraph_metrics 的 inference_* 列（token 数/状态/真实异常
  时间）；固定原因说明由固定状态合同投影，不建原因词典表
- 主题建模完成事实写 analysis_runs.topic_completed_at
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import Table, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from src.config import settings
from src.config.paths import resolve_model_dir, resolve_project_root
from src.storage.models import (
    AnalysisRun,
    Chapter,
    Paragraph,
    ParagraphMetric,
    ParagraphTopic,
)
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


@dataclass(frozen=True)
class TopicModelRunContract:
    """主题模型读取模型（attribute 面与旧契约一致，来源改为 analysis_runs.lda_*）

    保持原有属性面（含 model_key / artifact_key / inference_paragraph_count），
    使下游按属性读取的代码零改动；三个投影值不落库，由实现合同、
    artifact 解析器与正式推断状态聚合得到。
    """

    run_id: str
    library_version: str
    pipeline_version: str
    num_topics: int
    passes: int
    iterations: int
    alpha: float
    eta: float
    random_state: int
    lda_batch_size: int
    minimum_probability: float
    dictionary_size: int
    training_document_count: int
    inference_paragraph_count: int
    model_key: str
    artifact_key: str
    created_at: datetime | None = None


def project_topic_model_key() -> str:
    """model_key 读投影：当前固定 LDA 实现的模型合同标识（src.topic.schema）"""
    from src.topic.schema import TOPIC_MODEL_KEY

    return TOPIC_MODEL_KEY


def project_topic_artifact_key(run_id: str) -> str:
    """artifact_key 读投影：按当前 resolve_model_dir 与项目根规则解析"""
    return str(resolve_model_dir(run_id).relative_to(resolve_project_root()).as_posix())


def _prior_scalar(raw: object, *, num_topics: int, field_name: str) -> float:
    """LDA 先验拆列：数值直接取；字符串选择器按 gensim 合同取对称先验 1/K

    当前算法合同允许 alpha/eta 传 "auto"/"symmetric"（settings 默认 auto）：
    symmetric 的合同值即 1/K；auto 表示训练时从语料学习非对称先验，学习
    结果是 K 维向量，当前合同列只保存标量，按初始化值 1/K 记录。
    """
    if isinstance(raw, str):
        if raw not in {"auto", "symmetric"}:
            raise ValueError(f"analysis_runs.lda_{field_name} 无法用标量表达的先验选择器: {raw!r}")
        if num_topics <= 0:
            raise ValueError(f"analysis_runs.lda_{field_name} 需要正数 num_topics，当前为 {num_topics}")
        return 1.0 / float(num_topics)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"analysis_runs.lda_{field_name} 必须是数值或 auto/symmetric，当前为 {raw!r}")
    return float(raw)


def _lda_parameter_columns(parameters: Mapping[str, Any], *, num_topics: int) -> dict[str, Any]:
    """parameters 拆分列：缺失键按当前算法合同（settings）补齐；K 只在 lda_num_topics 列"""
    return {
        "lda_passes": int(parameters.get("passes") or settings.topic_model.passes),
        "lda_iterations": int(parameters.get("iterations") or settings.topic_model.iterations),
        "lda_alpha": _prior_scalar(
            parameters.get("alpha", settings.topic_model.lda.alpha), num_topics=num_topics, field_name="alpha"
        ),
        "lda_eta": _prior_scalar(
            parameters.get("eta", settings.topic_model.lda.eta), num_topics=num_topics, field_name="eta"
        ),
        "lda_random_state": int(parameters.get("random_state") or settings.topic_model.lda.random_state),
        "lda_batch_size": int(parameters.get("lda_batch_size") or settings.topic_model.lda.lda_batch_size),
        "lda_minimum_probability": float(
            parameters.get("minimum_probability", settings.topic_model.lda.minimum_probability)
        ),
    }


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
    """写入 run 的 LDA 实际构建事实（analysis_runs.lda_* 具名列）

    model_key/artifact_key/inference_paragraph_count 为合同投影，不再落列
    （inference_paragraph_count 由推断状态聚合、artifact 由解析器投影）。
    model_key 与当前固定实现不一致时报错，避免静默写错模型身份。
    写入同时登记主题阶段真实完成事实 topic_completed_at。
    """
    expected_model_key = project_topic_model_key()
    if model_key != expected_model_key:
        raise ValueError(
            f"LDA 模型身份是固定实现合同投影，当前仅支持 {expected_model_key!r}，收到 {model_key!r}"
        )
    session.execute(
        update(AnalysisRun)
        .where(AnalysisRun.run_id == run_id)
        .values(
            lda_library_version=library_version,
            lda_pipeline_version=pipeline_version,
            lda_num_topics=int(num_topics),
            lda_dictionary_size=int(dictionary_size),
            lda_training_document_count=int(training_document_count),
            lda_created_at=_utcnow(),
            topic_completed_at=_utcnow(),
            **_lda_parameter_columns(parameters, num_topics=num_topics),
        )
    )


def fetch_complete_inference_count(session: Session, run_id: str) -> int:
    """inference_paragraph_count 读投影：正式推断状态为 complete 的段落数"""
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
    """读取 run 的 LDA 实际构建行（含 model_key/artifact_key/推断段落数投影）"""
    row = session.execute(
        select(
            AnalysisRun.lda_library_version,
            AnalysisRun.lda_pipeline_version,
            AnalysisRun.lda_num_topics,
            AnalysisRun.lda_dictionary_size,
            AnalysisRun.lda_training_document_count,
            AnalysisRun.lda_passes,
            AnalysisRun.lda_iterations,
            AnalysisRun.lda_alpha,
            AnalysisRun.lda_eta,
            AnalysisRun.lda_random_state,
            AnalysisRun.lda_batch_size,
            AnalysisRun.lda_minimum_probability,
            AnalysisRun.lda_created_at,
        ).where(AnalysisRun.run_id == run_id)
    ).one_or_none()
    if row is None or row.lda_num_topics is None:
        return None
    return TopicModelRunContract(
        run_id=run_id,
        library_version=str(row.lda_library_version or ""),
        pipeline_version=str(row.lda_pipeline_version or ""),
        num_topics=int(row.lda_num_topics),
        passes=int(row.lda_passes or 0),
        iterations=int(row.lda_iterations or 0),
        alpha=float(row.lda_alpha or 0.0),
        eta=float(row.lda_eta or 0.0),
        random_state=int(row.lda_random_state or 0),
        lda_batch_size=int(row.lda_batch_size or 0),
        minimum_probability=float(row.lda_minimum_probability or 0.0),
        dictionary_size=int(row.lda_dictionary_size or 0),
        training_document_count=int(row.lda_training_document_count or 0),
        inference_paragraph_count=fetch_complete_inference_count(session, run_id),
        model_key=project_topic_model_key(),
        artifact_key=project_topic_artifact_key(run_id),
        created_at=row.lda_created_at,
    )


def insert_paragraph_topic_inferences(
    session: Session,
    run_id: str,
    rows: Sequence[tuple[int, int, int, str, str | None, float | None]],
) -> int:
    """
    全量 upsert 写入 run 的段落推断事实（paragraph_metrics.inference_* 列）

    rows: (paragraph_id, source_token_count, inference_token_count,
           inference_status, unavailable_reason, distribution_sum)

    只写正式事实（推断 token 数与状态）：source_token_count 从
    paragraph_metrics.token_count 读、固定说明由固定状态合同投影、
    distribution_sum 由正式 K 维权重聚合，三者写入时一律忽略。
    真实异常文字（error_text）只在状态为 failed 且有实际消息时写入。

    重跑语义：rows 覆盖本 run 全部段落（调用方按 fetch_paragraph_rows 全量构造），
    逐行覆盖旧推断事实即完成重新计算。禁止在 upsert 前做全量"清空推断列"的
    UPDATE：paragraph_metrics 上的延迟约束触发器
    trg_dc_paragraph_metric_inference_rows 在提交时按每条修改行的当时版本校验
    （计数读提交时的最终主题行）——清空会把旧 complete 行记成 status=<NULL>
    修改事件，与重跑写入的最终主题行形成假冲突，任何同 run 重跑都会在提交
    瞬间被拒（2026-10-17 run 52cbb1ac 实证：topic 阶段完整跑完、
    提交时 CheckViolation '非 complete 段落不得留主题行 ... status=<NULL> rows=25'）。
    """
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
    """清空 run 的段落推断状态列（纯清理场景专用）

    禁止把它当作"重跑先清"步骤：全量清空会产生 complete→NULL 修改事件，
    与随后重跑写入的最终主题行在提交时假冲突（延迟约束触发器按修改行当时
    版本校验，见 insert_paragraph_topic_inferences docstring）；重跑覆盖
    统一走 insert_paragraph_topic_inferences 的全量 upsert。
    """
    session.execute(
        update(ParagraphMetric).where(ParagraphMetric.run_id == run_id).values(**dict.fromkeys(_INFERENCE_COLUMNS))
    )


def fetch_topic_inference_total(session: Session, run_id: str) -> int | None:
    """全书主题推断分母：所有段落的 inference_token_count 之和"""
    return session.execute(
        select(func.sum(ParagraphMetric.inference_token_count)).where(ParagraphMetric.run_id == run_id)
    ).scalar_one_or_none()


def fetch_chapter_inference_totals(session: Session, run_id: str) -> Sequence[Row]:
    """按章节返回推断 token 分母（每段一格，§5.11 章节聚合分母）"""
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
            (ParagraphMetric.run_id == Paragraph.run_id)
            & (ParagraphMetric.paragraph_id == Paragraph.paragraph_id),
        )
        .where(Paragraph.run_id == run_id)
        .group_by(Chapter.chapter_id, Chapter.sequence, Chapter.title)
        .order_by(Chapter.sequence)
    )
    return session.execute(stmt).all()


def fetch_topic_emotion_aggregates(session: Session, run_id: str) -> Sequence[Row]:
    """主题-情感分子分母（§5.11）：净密度为 NULL 的段落在 SQL 层同时排除

    净密度由指标分子/分母的读投影给出（token_count=0 或指标行缺失即 NULL），
    因此过滤条件等价于旧的 "曲线净密度非空"。
    """
    net_density = net_density_projection()
    stmt = (
        select(
            ParagraphTopic.topic_id,
            func.sum(
                ParagraphTopic.topic_weight
                * ParagraphMetric.inference_token_count
                * net_density
            ).label("emotion_total"),
            func.sum(ParagraphTopic.topic_weight * ParagraphMetric.inference_token_count).label(
                "weighted_token_total"
            ),
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
    # __table__ 静态类型是 FromClause，运行期是映射的真实 Table（行插入需要它）
    session.execute(cast(Table, ParagraphTopic.__table__).insert(), topic_rows)
    return len(topic_rows)


def clear_paragraph_topics(session: Session, run_id: str) -> None:
    """清空 run 的段落主题行"""
    session.execute(delete(ParagraphTopic).where(ParagraphTopic.run_id == run_id))


def fetch_paragraph_topics_agg(session: Session, run_id: str) -> Sequence[Row]:
    """
    全书主题分子：按主题返回 token 加权和（§5.11）

    分母为全书所有段落的 inference_token_count 之和，
    由 fetch_topic_inference_total 提供；归一化在调用方完成。
    禁止对段落等权求和。
    """
    stmt = (
        select(
            ParagraphTopic.topic_id,
            func.sum(ParagraphTopic.topic_weight * ParagraphMetric.inference_token_count).label(
                "weighted_total"
            ),
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
            func.sum(ParagraphTopic.topic_weight * ParagraphMetric.inference_token_count).label(
                "weighted_total"
            ),
        )
        .select_from(Chapter)
        .join(Paragraph, (Paragraph.run_id == Chapter.run_id) & (Paragraph.chapter_id == Chapter.chapter_id))
        .join(
            ParagraphMetric,
            (ParagraphMetric.run_id == Paragraph.run_id)
            & (ParagraphMetric.paragraph_id == Paragraph.paragraph_id),
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

    全文起点由 chapters.char_offset + 段落章内起点投影；
    返回: (paragraph_id, chapter_id, chapter_sequence, global_start_char,
           inference_token_count, topic_id, topic_weight)
    """
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
            (ParagraphMetric.run_id == Paragraph.run_id)
            & (ParagraphMetric.paragraph_id == Paragraph.paragraph_id),
        )
        .join(
            ParagraphTopic,
            (ParagraphTopic.run_id == Paragraph.run_id)
            & (ParagraphTopic.paragraph_id == Paragraph.paragraph_id),
        )
        .where(Paragraph.run_id == run_id)
        .order_by(global_start_char, ParagraphTopic.topic_id)
    )
    return session.execute(stmt).all()
