"公开访问能力的包内适配，Repository 和映射对象不越过返回边界"

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from src.config.constants.contracts import FIXED_CONTRACT_VERSION
from src.storage.input_boundary import plain_inputs
from src.storage.records.annotation import (
    AnnotationRoleRecord,
    DialogueRecordRow,
    ForeshadowingEdgeRow,
    GraphFactRow,
    SavedAnnotationRecord,
)
from src.storage.records.cases import CaseSave
from src.storage.records.embedding_ops import ParagraphEmbeddingRow
from src.storage.records.graph import (
    ChapterBoundary,
    EntitySnapshotRow,
    GraphChangeRow,
    GraphSnapshotRow,
    RelationSnapshotRow,
)
from src.storage.records.inputs import ChapterRecord as ChapterData
from src.storage.records.inputs import ChunkRecord as Chunk
from src.storage.records.inputs import ParagraphRecord as ParagraphSpan
from src.storage.records.models import ChapterRecord, EventDeclarationRecord, GraphEntityRecord
from src.storage.records.paragraph import ParagraphCurveRow, ParagraphMetricRow
from src.storage.records.sentinels import UNSET as _UNSET
from src.storage.records.topic import TopicModelRunContract
from src.storage.records.values import NamedRecord
from src.storage.repositories.annotation.repository import AnnotationRepository as _AnnotationRepository
from src.storage.repositories.chapter_repository import ChapterRepository as _ChapterRepository
from src.storage.repositories.diagnosis_repository import DiagnosisRepository as _DiagnosisRepository
from src.storage.repositories.graph.event_forest import EventForestRecords as _EventForestRecords
from src.storage.repositories.graph.repository import GraphRepository as _GraphRepository
from src.storage.repositories.linguistic_repository import LinguisticRepository as _LinguisticRepository
from src.storage.repositories.paragraph_repository import ParagraphRepository as _ParagraphRepository
from src.storage.repositories.run_repository import RunRepository as _RunRepository
from src.storage.repositories.stats.repository import StatsRepository as _StatsRepository


@plain_inputs
class RunAccess:
    "绑定一个内部事务的数据访问实现"

    def __init__(self, runner):
        self._runner = runner

    def create_run(
        self,
        novel_id: str,
        source_path: str | None = None,
        title: str | None = None,
        author: str | None = None,
        run_id: str | None = None,
        task_kind: str = "analysis",
        request_payload: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> str:
        "创建新的分析运行记录"
        return self._runner.run(
            lambda _session: _RunRepository(_session).create_run(
                novel_id, source_path, title, author, run_id, task_kind, request_payload, task_id=task_id
            ),
            read_only=False,
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        "获取运行记录"
        return self._runner.run(lambda _session: _RunRepository(_session).get_run(run_id), read_only=True)

    def get_runs_by_novel(self, novel_id: str) -> list[dict[str, Any]]:
        "获取指定小说的所有运行记录"
        return self._runner.run(lambda _session: _RunRepository(_session).get_runs_by_novel(novel_id), read_only=True)

    def request_task_cancellation(self, run_id: str) -> str | None:
        "原子性地把可取消任务推进到 cancelling"
        return self._runner.run(
            lambda _session: _RunRepository(_session).request_task_cancellation(run_id), read_only=False
        )

    def get_by_status(self, status: str) -> list[dict[str, Any]]:
        "按状态查询任务。Args: status；Returns: 任务记录列表"
        return self._runner.run(lambda _session: _RunRepository(_session).get_by_status(status), read_only=True)

    def get_pending_tasks(self) -> list[dict[str, Any]]:
        "获取所有 pending 任务"
        return self._runner.run(lambda _session: _RunRepository(_session).get_pending_tasks(), read_only=True)

    def claim_pending_run(self, run_id: str, *, worker_id: str, heartbeat_at: datetime | None = None) -> bool:
        "原子性领取一个尚未执行的 pending 任务"
        return self._runner.run(
            lambda _session: _RunRepository(_session).claim_pending_run(
                run_id, worker_id=worker_id, heartbeat_at=heartbeat_at
            ),
            read_only=False,
        )

    def cancel_unclaimed_pending_run(self, run_id: str, *, message: str) -> bool:
        "原子性终结尚未被任何 worker 领取的 pending 任务"
        return self._runner.run(
            lambda _session: _RunRepository(_session).cancel_unclaimed_pending_run(run_id, message=message),
            read_only=False,
        )

    def update_run_task_fields(
        self,
        run_id: str,
        *,
        status: str | None | object = _UNSET,
        progress: float | None | object = _UNSET,
        stage: str | None | object = _UNSET,
        sub_stage: str | None | object = _UNSET,
        current: int | None | object = _UNSET,
        total: int | None | object = _UNSET,
        message: str | None | object = _UNSET,
        error: str | None | object = _UNSET,
        task_kind: str | None | object = _UNSET,
        request_payload: dict[str, Any] | None | object = _UNSET,
        cancel_requested: bool | None | object = _UNSET,
        worker_id: str | None | object = _UNSET,
        heartbeat_at: datetime | None | object = _UNSET,
        started_at: datetime | None | object = _UNSET,
        completed_at: datetime | None | object = _UNSET,
    ) -> None:
        "批量更新运行态字段（仅写入显式传入的字段）"
        return self._runner.run(
            lambda _session: _RunRepository(_session).update_run_task_fields(
                run_id,
                status=status,
                progress=progress,
                stage=stage,
                sub_stage=sub_stage,
                current=current,
                total=total,
                message=message,
                error=error,
                task_kind=task_kind,
                request_payload=request_payload,
                cancel_requested=cancel_requested,
                worker_id=worker_id,
                heartbeat_at=heartbeat_at,
                started_at=started_at,
                completed_at=completed_at,
            ),
            read_only=False,
        )

    def get_run_by_task_id(self, task_id: str) -> dict[str, Any] | None:
        "按 run_id 前缀查询（LIKE 转义 %/_/\\"
        return self._runner.run(lambda _session: _RunRepository(_session).get_run_by_task_id(task_id), read_only=True)

    def delete_run(self, run_id: str) -> bool:
        "按运行范围删除全部 run 级数据，由调用方统一提交"
        return self._runner.run(lambda _session: _RunRepository(_session).delete_run(run_id), read_only=False)

    def mark_running_as_failed(self) -> int:
        "启动时把所有 running 任务标记为 failed"
        return self._runner.run(lambda _session: _RunRepository(_session).mark_running_as_failed(), read_only=False)

    def mark_cancelling_as_cancelled(self) -> int:
        "启动时把所有 cancelling 任务收口为 cancelled"
        return self._runner.run(
            lambda _session: _RunRepository(_session).mark_cancelling_as_cancelled(), read_only=False
        )


@plain_inputs
class ChapterAccess:
    "绑定一个内部事务的数据访问实现"

    def __init__(self, runner):
        self._runner = runner

    def insert_chapters(self, run_id: str, chapters: Sequence[ChapterData]) -> None:
        "批量插入章节目录，插入前先删除该 run_id 的旧数据"
        return self._runner.run(
            lambda _session: _ChapterRepository(_session).insert_chapters(run_id, chapters), read_only=False
        )

    def insert_chapter_texts(self, run_id: str, chunks: Sequence[Chunk]) -> None:
        "按章节回填正文切片（chapters.char_offset/text，与目录同键一行）"
        return self._runner.run(
            lambda _session: _ChapterRepository(_session).insert_chapter_texts(run_id, chunks), read_only=False
        )

    def fetch_chapters(self, run_id: str) -> Sequence[ChapterRecord]:
        "按顺序读取指定 run 的章节目录"
        return self._runner.run(lambda _session: _ChapterRepository(_session).fetch_chapters(run_id), read_only=True)

    def fetch_chapter_texts(self, run_id: str) -> list[tuple[int, str]]:
        "获取所有有正文章节的文本，按章节 sequence 升序"
        return self._runner.run(
            lambda _session: _ChapterRepository(_session).fetch_chapter_texts(run_id), read_only=True
        )

    def fetch_chapter_bodies(self, run_id: str) -> Sequence[NamedRecord]:
        "获取 run 的章节正文行（章序 + 正文起点 + 正文终点投影 + 文本）"
        return self._runner.run(
            lambda _session: _ChapterRepository(_session).fetch_chapter_bodies(run_id), read_only=True
        )

    def fetch_chapter_counts(self, run_id: str) -> tuple[int, int]:
        "获取有正文章节的数量与总字符数"
        return self._runner.run(
            lambda _session: _ChapterRepository(_session).fetch_chapter_counts(run_id), read_only=True
        )

    def fetch_all_chapter_texts(self, run_id: str) -> list[str]:
        "获取指定运行的所有章节正文文本（仅文本）"
        return self._runner.run(
            lambda _session: _ChapterRepository(_session).fetch_all_chapter_texts(run_id), read_only=True
        )

    def count_chapters(self, run_id: str) -> int:
        "统计指定运行的有正文章节数量（空正文章节无正文，不计入）"
        return self._runner.run(lambda _session: _ChapterRepository(_session).count_chapters(run_id), read_only=True)

    def has_chapters(self, run_id: str) -> bool:
        "检查指定运行是否有正文数据"
        return self._runner.run(lambda _session: _ChapterRepository(_session).has_chapters(run_id), read_only=True)


@plain_inputs
class ParagraphAccess:
    "绑定一个内部事务的数据访问实现"

    def __init__(self, runner):
        self._runner = runner

    def save_topics(
        self, run_id: str, *, model: dict[str, Any], inferences: Sequence[tuple], topics: Sequence[tuple]
    ) -> int:
        "模型事实、段落推断和完整分布在一个事务中保存，提交时统一校验延迟约束"

        def save(session):
            repository = _ParagraphRepository(session)
            repository.insert_topic_model_run(run_id, **model)
            repository.clear_paragraph_topics(run_id)
            repository.insert_paragraph_topic_inferences(run_id, inferences)
            return repository.insert_paragraph_topics(run_id, topics)

        return self._runner.run(save)

    def insert_paragraphs(self, run_id: str, spans: Sequence[ParagraphSpan]) -> int:
        "先删后插写入 run 的段落行（插入前校验不变量）"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).insert_paragraphs(run_id, spans), read_only=False
        )

    def has_paragraphs(self, run_id: str) -> bool:
        "run 是否存在段落行"
        return self._runner.run(lambda _session: _ParagraphRepository(_session).has_paragraphs(run_id), read_only=True)

    def count_paragraphs(self, run_id: str) -> int:
        "统计指定 run 的段落行数"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).count_paragraphs(run_id), read_only=True
        )

    def fetch_paragraph_rows(self, run_id: str) -> Sequence[NamedRecord]:
        "读取 run 的全部段落行，按 paragraph_id 升序"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).fetch_paragraph_rows(run_id), read_only=True
        )

    def fetch_paragraph_rows_batch(
        self, run_id: str, *, chapter_id: int | None = None, after_id: int | None = None, limit: int | None = 128
    ) -> Sequence[NamedRecord]:
        "按 paragraph_id keyset 游标分批读取段落行"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).fetch_paragraph_rows_batch(
                run_id, chapter_id=chapter_id, after_id=after_id, limit=limit
            ),
            read_only=True,
        )

    def save_metrics(self, run_id, metrics, tension, function_words, semantic_categories):
        "同一批指标、张力及分类观测作为完整操作提交"
        from src.storage.repositories.paragraph.writer import (
            insert_paragraph_function_word_counts,
            insert_paragraph_semantic_category_counts,
            insert_paragraph_tension_observations,
        )

        def operation(session):
            result = _ParagraphRepository(session).insert_paragraph_metrics(run_id, metrics)
            insert_paragraph_tension_observations(session, run_id, tension)
            insert_paragraph_function_word_counts(session, run_id, function_words)
            insert_paragraph_semantic_category_counts(session, run_id, semantic_categories)
            return result

        return self._runner.run(operation)

    def insert_paragraph_metrics(self, run_id: str, rows: Sequence[ParagraphMetricRow]) -> int:
        "先删后插写入 run 的段落指标行（基础计数与充分统计量；派生观测不随本行写入）"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).insert_paragraph_metrics(run_id, rows), read_only=False
        )

    def fetch_paragraph_metrics(self, run_id: str) -> Sequence[NamedRecord]:
        "读取 run 的全部段落指标行，按 paragraph_id 升序"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).fetch_paragraph_metrics(run_id), read_only=True
        )

    def has_paragraph_metrics(self, run_id: str) -> bool:
        "run 是否存在段落指标行"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).has_paragraph_metrics(run_id), read_only=True
        )

    def fetch_chapter_metric_aggregates(self, run_id: str) -> list[tuple[int, dict[str, float]]]:
        "按章聚合段落指标充分统计量（ 分子/分母守恒；char_count 为正文长度投影）"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).fetch_chapter_metric_aggregates(run_id), read_only=True
        )

    def insert_topic_model_run(
        self,
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
        "把 run 的 LDA 实际构建写入 analysis_runs.lda_*（model_key/artifact_key 为合同投影）"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).insert_topic_model_run(
                run_id,
                model_key=model_key,
                library_version=library_version,
                pipeline_version=pipeline_version,
                num_topics=num_topics,
                parameters=parameters,
                dictionary_size=dictionary_size,
                training_document_count=training_document_count,
                inference_paragraph_count=inference_paragraph_count,
                artifact_key=artifact_key,
            ),
            read_only=False,
        )

    def fetch_topic_model_run(self, run_id: str) -> TopicModelRunContract | None:
        "读取 run 的 LDA 实际构建行（analysis_runs.lda_* + 合同投影）"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).fetch_topic_model_run(run_id), read_only=True
        )

    def insert_paragraph_topic_inferences(
        self, run_id: str, rows: Sequence[tuple[int, int, int, str, str | None, float | None]]
    ) -> int:
        "先清后插写入 run 的段落推断状态（paragraph_metrics.inference_*，每段一行）"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).insert_paragraph_topic_inferences(run_id, rows),
            read_only=False,
        )

    def clear_paragraph_topic_inferences(self, run_id: str) -> None:
        "清空 run 的段落推断状态列（paragraph_metrics.inference_*）"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).clear_paragraph_topic_inferences(run_id), read_only=False
        )

    def fetch_topic_inference_total(self, run_id: str) -> int | None:
        "全书主题推断分母：所有段落（每段一行）的 inference_token_count 之和"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).fetch_topic_inference_total(run_id), read_only=True
        )

    def fetch_chapter_inference_totals(self, run_id: str) -> Sequence[NamedRecord]:
        "按章节返回推断 token 分母（每段一行， 章节聚合分母）"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).fetch_chapter_inference_totals(run_id), read_only=True
        )

    def fetch_topic_emotion_aggregates(self, run_id: str) -> Sequence[NamedRecord]:
        "主题-情感分子分母：net_density 空值段落在 SQL 层同时排除"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).fetch_topic_emotion_aggregates(run_id), read_only=True
        )

    def insert_paragraph_topics(self, run_id: str, rows: Sequence[tuple[int, int, float]]) -> int:
        '先清后插写入 run 的段落主题行（同 run 重跑语义是"重新计算"）'
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).insert_paragraph_topics(run_id, rows), read_only=False
        )

    def clear_paragraph_topics(self, run_id: str) -> None:
        "清空 run 的段落主题行"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).clear_paragraph_topics(run_id), read_only=False
        )

    def fetch_paragraph_topics_agg(self, run_id: str) -> Sequence[NamedRecord]:
        "全书主题分子：按主题返回 token 加权和（，禁止对段落等权求和）"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).fetch_paragraph_topics_agg(run_id), read_only=True
        )

    def fetch_chapter_topic_aggregates(self, run_id: str) -> Sequence[NamedRecord]:
        "章节主题分子：按章节返回主题 token 加权和"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).fetch_chapter_topic_aggregates(run_id), read_only=True
        )

    def fetch_paragraph_topic_rows(self, run_id: str) -> Sequence[NamedRecord]:
        "段落主题序列数据：段落真实字符位置、章节序列与推断 token 数齐备"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).fetch_paragraph_topic_rows(run_id), read_only=True
        )

    def insert_paragraph_curves(self, run_id: str, rows: Sequence[ParagraphCurveRow]) -> int:
        "先删后插写入 run 的段落曲线平滑行（paragraph_features 两类标量行，缺值保持 NULL）"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).insert_paragraph_curves(run_id, rows), read_only=False
        )

    def fetch_paragraph_curves(self, run_id: str) -> Sequence[NamedRecord]:
        "读取 run 的全部段落曲线行（密度/张力为读投影，平滑值取特征行）"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).fetch_paragraph_curves(run_id), read_only=True
        )

    def fetch_chapter_tension_scores(self, run_id: str) -> list[tuple[int, float]]:
        "每章张力 = 章内段落 surface_tension 均值（供 timeline/聚合使用）"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).fetch_chapter_tension_scores(run_id), read_only=True
        )

    def has_paragraph_curves(self, run_id: str) -> bool:
        "run 是否存在段落曲线平滑样本行"
        return self._runner.run(
            lambda _session: _ParagraphRepository(_session).has_paragraph_curves(run_id), read_only=True
        )

    def insert_paragraph_embeddings(
        self, run_id: str, rows: Iterable[ParagraphEmbeddingRow], embedding_dimension: int | None = None
    ):
        "执行具名段落操作，结果在事务结束前转为普通记录"
        from src.storage.repositories.paragraph.embedding_ops import insert_paragraph_embeddings

        return self._runner.run(
            lambda session: insert_paragraph_embeddings(session, run_id, rows, embedding_dimension), read_only=False
        )

    def search_similar_paragraphs(
        self,
        run_id: str,
        query_embedding: list[float],
        top_k: int = 5,
        similarity_threshold: float = 0.7,
        exclude_paragraph_ids: Sequence[int] | None = None,
        min_paragraph_id: int | None = None,
        max_paragraph_id: int | None = None,
        before_chapter_sequence: int | None = None,
        after_chapter_sequence: int | None = None,
    ):
        "执行具名段落操作，结果在事务结束前转为普通记录"
        from src.storage.repositories.paragraph.embedding_ops import search_similar_paragraphs

        return self._runner.run(
            lambda session: search_similar_paragraphs(
                session,
                run_id,
                query_embedding,
                top_k,
                similarity_threshold,
                exclude_paragraph_ids,
                min_paragraph_id,
                max_paragraph_id,
                before_chapter_sequence,
                after_chapter_sequence,
            ),
            read_only=True,
        )

    def has_paragraph_embeddings(self, run_id: str):
        "执行具名段落操作，结果在事务结束前转为普通记录"
        from src.storage.repositories.paragraph.embedding_ops import has_paragraph_embeddings

        return self._runner.run(lambda session: has_paragraph_embeddings(session, run_id), read_only=True)

    def get_incomplete_paragraph_embedding_paragraph_ids(self, run_id: str):
        "执行具名段落操作，结果在事务结束前转为普通记录"
        from src.storage.repositories.paragraph.embedding_ops import get_incomplete_paragraph_embedding_paragraph_ids

        return self._runner.run(
            lambda session: get_incomplete_paragraph_embedding_paragraph_ids(session, run_id), read_only=True
        )

    def search_paragraphs_by_keywords(
        self,
        run_id: str,
        keywords: Sequence[str],
        top_k: int = 10,
        exclude_paragraph_ids: Sequence[int] | None = None,
        min_paragraph_id: int | None = None,
        max_paragraph_id: int | None = None,
        before_chapter_sequence: int | None = None,
        after_chapter_sequence: int | None = None,
    ):
        "执行具名段落操作，结果在事务结束前转为普通记录"
        from src.storage.repositories.paragraph.keyword_ops import search_paragraphs_by_keywords

        return self._runner.run(
            lambda session: search_paragraphs_by_keywords(
                session,
                run_id,
                keywords,
                top_k,
                exclude_paragraph_ids,
                min_paragraph_id,
                max_paragraph_id,
                before_chapter_sequence,
                after_chapter_sequence,
            ),
            read_only=True,
        )

    def fetch_global_stat_rows(self, run_id: str):
        "执行具名段落操作，结果在事务结束前转为普通记录"
        from src.storage.repositories.metric_inputs import fetch_global_stat_rows

        return self._runner.run(lambda session: fetch_global_stat_rows(session, run_id), read_only=True)


@plain_inputs
class AnnotationAccess:
    "绑定一个内部事务的数据访问实现"

    def __init__(self, runner):
        self._runner = runner

    def discard_chapters(self, run_id: str, chapter_ids: set[int]):
        "正式恢复入口按章整体清退，成功提交后才恢复内存视图"
        from src.storage.repositories.annotation_recovery import discard_chapters

        return self._runner.run(lambda session: discard_chapters(session, run_id, chapter_ids))

    def inspect_saved(self, invocation_id: str):
        "独立核验真实执行归属与正式产物是否存在"
        from src.storage.repositories.annotation_receipts import inspect_saved

        return self._runner.run(lambda session: inspect_saved(session, invocation_id), read_only=True)

    def consolidate(self, request: dict):
        "验证冻结来源并整体保存章末凭据和案例"
        from src.storage.repositories.annotation_receipts import save_consolidation

        return self._runner.run(lambda session: save_consolidation(session, request))

    def save(self, request):
        "标注记录、事实、声明、对话、标签和案例在同一事务内提交"
        from src.storage.repositories.annotation_writes import save_annotation

        return self._runner.run(lambda session: save_annotation(session, request))

    def fetch_chapter_sequence_map(self, run_id: str) -> dict[int, int]:
        "Annotation 数据访问"
        return self._runner.run(
            lambda _session: _AnnotationRepository(_session).fetch_chapter_sequence_map(run_id), read_only=True
        )

    def fetch_chapter_ids(self, run_id: str) -> set[int]:
        "Annotation 数据访问"
        return self._runner.run(
            lambda _session: _AnnotationRepository(_session).fetch_chapter_ids(run_id), read_only=True
        )

    def fetch_saved_outputs(self, run_id: str) -> list[SavedAnnotationRecord]:
        "本运行已正式保存的章节标注：行存在即保存事实，章号/角色取记录自身列"
        return self._runner.run(
            lambda _session: _AnnotationRepository(_session).fetch_saved_outputs(run_id), read_only=True
        )

    def fetch_role_records(self, run_id: str) -> list[AnnotationRoleRecord]:
        "本运行的章内标注角色：state 由正式标注记录的存在性表达，执行号取产物行自身"
        return self._runner.run(
            lambda _session: _AnnotationRepository(_session).fetch_role_records(run_id), read_only=True
        )

    def fetch_entities_by_id(self, run_id: str) -> dict[str, GraphEntityRecord]:
        "Annotation 数据访问"
        return self._runner.run(
            lambda _session: _AnnotationRepository(_session).fetch_entities_by_id(run_id), read_only=True
        )

    def fetch_dialogue_records(self, run_id: str) -> list[DialogueRecordRow]:
        "本运行对话记录：run/章是创建时自落归属，内容按章节区间精确切片"
        return self._runner.run(
            lambda _session: _AnnotationRepository(_session).fetch_dialogue_records(run_id), read_only=True
        )

    def fetch_foreshadowing_roots(self, run_id: str, *, ordered: bool = False) -> list[EventDeclarationRecord]:
        "Annotation 数据访问"
        return self._runner.run(
            lambda _session: _AnnotationRepository(_session).fetch_foreshadowing_roots(run_id, ordered=ordered),
            read_only=True,
        )

    def fetch_foreshadowing_edges(self, run_id: str, *, ordered: bool = False) -> list[ForeshadowingEdgeRow]:
        "伏笔语义链路读投影；ordered 时按目标事件来源章序排序（无证据章的链路排后）"
        return self._runner.run(
            lambda _session: _AnnotationRepository(_session).fetch_foreshadowing_edges(run_id, ordered=ordered),
            read_only=True,
        )

    def fetch_event_records(self, run_id: str, event_ids: set[str]) -> list[EventDeclarationRecord]:
        "Annotation 数据访问"
        return self._runner.run(
            lambda _session: _AnnotationRepository(_session).fetch_event_records(run_id, event_ids), read_only=True
        )

    def fetch_foreshadowing_edge_counts(self, run_id: str) -> dict[str, int]:
        "Annotation 数据访问"
        return self._runner.run(
            lambda _session: _AnnotationRepository(_session).fetch_foreshadowing_edge_counts(run_id), read_only=True
        )

    def fetch_graph_facts(self, run_id: str, *, content_kind: str) -> list[GraphFactRow]:
        "本运行指定形状的正式图贡献事实（旧内容类型名映射到冻结形状列）"
        return self._runner.run(
            lambda _session: _AnnotationRepository(_session).fetch_graph_facts(run_id, content_kind=content_kind),
            read_only=True,
        )


@plain_inputs
class GraphAccess:
    "绑定一个内部事务的数据访问实现"

    def __init__(self, runner, *, internal: bool = False):
        self._runner = runner
        self._internal = internal

    def run_exists(self, run_id: str) -> bool:
        return self._runner.run(
            lambda _session: _GraphRepository(_session, internal=self._internal).run_exists(run_id), read_only=True
        )

    def resolve_chapter_boundary(self, run_id: str, *, chapter_id: int | None = None) -> ChapterBoundary | None:
        "用于解析显式章节或当前运行最后章节"
        return self._runner.run(
            lambda _session: _GraphRepository(_session, internal=self._internal).resolve_chapter_boundary(
                run_id, chapter_id=chapter_id
            ),
            read_only=True,
        )

    def resolve_persisted_boundary(self, run_id: str) -> ChapterBoundary | None:
        "用于构造覆盖全部已提交数据的历史边界（不依赖 annotation record）"
        return self._runner.run(
            lambda _session: _GraphRepository(_session, internal=self._internal).resolve_persisted_boundary(run_id),
            read_only=True,
        )

    def fetch_entity_snapshots(self, boundary: ChapterBoundary) -> list[EntitySnapshotRow]:
        "用于选择目标章节以前最近状态并继承无变化实体"
        return self._runner.run(
            lambda _session: _GraphRepository(_session, internal=self._internal).fetch_entity_snapshots(boundary),
            read_only=True,
        )

    def fetch_relation_snapshots(
        self, boundary: ChapterBoundary, *, active_only: bool = True
    ) -> list[RelationSnapshotRow]:
        "用于选择目标章节以前最近关系状态并过滤活动状态"
        return self._runner.run(
            lambda _session: _GraphRepository(_session, internal=self._internal).fetch_relation_snapshots(
                boundary, active_only=active_only
            ),
            read_only=True,
        )

    def fetch_snapshot(self, run_id: str, *, chapter_id: int | None = None) -> GraphSnapshotRow | None:
        "用于返回目标章节边界的实体状态与有效关系"
        return self._runner.run(
            lambda _session: _GraphRepository(_session, internal=self._internal).fetch_snapshot(
                run_id, chapter_id=chapter_id
            ),
            read_only=True,
        )

    def fetch_changes(
        self, run_id: str, *, chapter_id: int | None = None, offset: int = 0, limit: int | None = 200
    ) -> tuple[list[GraphChangeRow], int]:
        "用于按章节倒序分页返回状态和关系变化"
        return self._runner.run(
            lambda _session: _GraphRepository(_session, internal=self._internal).fetch_changes(
                run_id, chapter_id=chapter_id, offset=offset, limit=limit
            ),
            read_only=True,
        )

    def fetch_latest_entity_rows(self, run_id: str, *, entity_type: str | None = None) -> list[EntitySnapshotRow]:
        "用于读取当前章节边界的实体状态"
        return self._runner.run(
            lambda _session: _GraphRepository(_session, internal=self._internal).fetch_latest_entity_rows(
                run_id, entity_type=entity_type
            ),
            read_only=True,
        )

    def fetch_latest_relations(self, run_id: str, *, active_only: bool = True) -> list[RelationSnapshotRow]:
        "用于读取当前章节边界的关系状态"
        return self._runner.run(
            lambda _session: _GraphRepository(_session, internal=self._internal).fetch_latest_relations(
                run_id, active_only=active_only
            ),
            read_only=True,
        )

    def fetch_relation_history(self, run_id: str) -> list[RelationSnapshotRow]:
        "按章节顺序读取关系历史，共享一次折叠结果，避免逐状态重建全图"
        return self._runner.run(
            lambda _session: _GraphRepository(_session, internal=self._internal).fetch_relation_history(run_id),
            read_only=True,
        )

    def fetch_relation_changes(self, run_id: str, *, limit: int | None = None) -> list[GraphChangeRow]:
        "用于读取诊断时间轴所需的关系变化事实"
        return self._runner.run(
            lambda _session: _GraphRepository(_session, internal=self._internal).fetch_relation_changes(
                run_id, limit=limit
            ),
            read_only=True,
        )

    def count_chapters(self, run_id: str) -> int:
        "用于统计当前运行已提交的章节数量"
        return self._runner.run(
            lambda _session: _GraphRepository(_session, internal=self._internal).count_chapters(run_id), read_only=True
        )


@plain_inputs
class DiagnosisAccess:
    "绑定一个内部事务的数据访问实现"

    def __init__(self, runner):
        self._runner = runner

    def save_session(self, request):
        "案例会话的事件、事实、归因、交付与执行终态一起提交"
        from src.storage.repositories.diagnosis_publish import save_session

        return self._runner.run(lambda session: save_session(session, request))

    def session_rows(self, run_id: str) -> dict:
        "恢复诊断草稿所需的具名记录，在同一只读事务中读取"
        from src.storage.repositories.diagnosis_publish import session_rows

        return self._runner.run(lambda session: session_rows(session, run_id), read_only=True)

    def publish(self, request):
        "正式诊断的所有关系由 Storage 保证原子提交"
        from src.storage.repositories.diagnosis_publish import publish

        return self._runner.run(lambda session: publish(session, request))

    def saved_case_warnings(self, run_id: str, report_id: str) -> dict:
        "读取已发布报告按执行归属的案例保存告警"
        from src.storage.repositories.diagnosis_publish import saved_case_warnings

        return self._runner.run(lambda session: saved_case_warnings(session, run_id, report_id), read_only=True)

    def register_session(self, *, run_id: str, session_id: str):
        "整轮身份在派发前独立提交"
        from src.storage.repositories.organization_writes import register_diagnosis_session

        return self._runner.run(
            lambda session: register_diagnosis_session(session, run_id=run_id, session_id=session_id)
        )

    def register_attempt(
        self,
        *,
        run_id: str,
        session_id: str,
        execution_id: str,
        role: str,
        attempt_number: int,
        case_anchor: str | None = None,
        case_registration: CaseSave | None = None,
    ):
        "会话与实际尝试身份一起登记，不向外提供事务对象"
        from src.storage.repositories.organization_writes import (
            register_diagnosis_execution,
            register_diagnosis_session,
        )

        def operation(session):
            register_diagnosis_session(session, run_id=run_id, session_id=session_id)
            if case_registration is not None:
                from src.storage.repositories.case_writes import CaseWritesRepository

                if case_registration.run_id != run_id:
                    raise ValueError("案例登记与执行不属于同一运行")
                warnings = CaseWritesRepository(run_id).save_work(session, case_registration)
                if warnings:
                    raise ValueError(f"案例执行登记失败: {warnings}")
            register_diagnosis_execution(
                session,
                run_id=run_id,
                execution_id=execution_id,
                role=role,
                attempt_number=attempt_number,
                case_anchor=case_anchor,
            )

        return self._runner.run(operation)

    def retain_pending(self, run_id: str, session_id: str, contributions):
        "失败登记独立保存，已发布的交付不可降级"
        from src.storage.repositories.diagnosis_publish import retain_pending

        return self._runner.run(lambda session: retain_pending(session, run_id, session_id, contributions))

    def next_attempt(self, run_id: str, role: str, case_anchor: str | None) -> int:
        "读取已登记的真实尝试数量"
        from src.storage.repositories.diagnosis_publish import next_attempt

        return self._runner.run(lambda session: next_attempt(session, run_id, role, case_anchor), read_only=True)

    def fetch_high_tension_chunks(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, float]]:
        "高张力诊断数据源为正式表面张力读数（ 事实定位段落化）"
        return self._runner.run(
            lambda _session: _DiagnosisRepository(_session).fetch_high_tension_chunks(run_id, limit), read_only=True
        )

    def fetch_topic_weights(self, run_id: str, top_n: int | None = None) -> list[dict[str, Any]]:
        "Diagnosis 数据访问"
        return self._runner.run(
            lambda _session: _DiagnosisRepository(_session).fetch_topic_weights(run_id, top_n), read_only=True
        )


@plain_inputs
class StatisticsAccess:
    "绑定一个内部事务的数据访问实现"

    def __init__(self, runner):
        self._runner = runner

    def insert_global_stats(self, run_id: str, stats: Iterable[tuple[str, float | None]]) -> None:
        "插入全局统计数据"
        return self._runner.run(
            lambda _session: _StatsRepository(_session).insert_global_stats(run_id, stats), read_only=False
        )

    def fetch_global_stats_dict(self, run_id: str) -> dict[str, float | None]:
        "获取全局统计数据字典"
        return self._runner.run(
            lambda _session: _StatsRepository(_session).fetch_global_stats_dict(run_id), read_only=True
        )

    def insert_model_turn(
        self,
        *,
        run_id: str,
        task_type: str,
        call_type: str,
        model: str,
        prompt_tokens: int,
        total_tokens: int,
        completion_tokens: int | None = None,
        chapter_id: int | None = None,
        cache_read_tokens: int | None = None,
        cost: float | None = None,
        accounting_source: str = "reported",
        reasoning_tokens: int | None = None,
        message_key: str | None = None,
    ) -> int:
        "插入非 Agent 模型调用记账行"
        return self._runner.run(
            lambda _session: _StatsRepository(_session).insert_model_turn(
                run_id=run_id,
                task_type=task_type,
                call_type=call_type,
                model=model,
                prompt_tokens=prompt_tokens,
                total_tokens=total_tokens,
                completion_tokens=completion_tokens,
                chapter_id=chapter_id,
                cache_read_tokens=cache_read_tokens,
                cost=cost,
                accounting_source=accounting_source,
                reasoning_tokens=reasoning_tokens,
                message_key=message_key,
            ),
            read_only=False,
        )

    def has_topic_data(self, run_id: str) -> bool:
        "检查指定运行是否有主题数据"
        return self._runner.run(lambda _session: _StatsRepository(_session).has_topic_data(run_id), read_only=True)

    def has_linguistic_data(self, run_id: str) -> bool:
        "检查指定运行是否有语言结构基础数据"
        return self._runner.run(lambda _session: _StatsRepository(_session).has_linguistic_data(run_id), read_only=True)

    def insert_agent_analysis(self, run_id: str, payload: Mapping[str, Any]) -> str:
        "诊断产物追加进分析产物表，返回产物 id"
        return self._runner.run(
            lambda _session: _StatsRepository(_session).insert_agent_analysis(run_id, payload), read_only=False
        )

    def fetch_agent_analysis(self, run_id: str) -> dict[str, Any] | None:
        "获取最新诊断产物"
        return self._runner.run(
            lambda _session: _StatsRepository(_session).fetch_agent_analysis(run_id), read_only=True
        )

    def fetch_novel_title(self, novel_id: str) -> str | None:
        "获取小说标题"
        return self._runner.run(lambda _session: _StatsRepository(_session).fetch_novel_title(novel_id), read_only=True)


@plain_inputs
class LinguisticAccess:
    "绑定一个内部事务的数据访问实现"

    def __init__(self, runner):
        self._runner = runner

    def ensure_ltp_contract(
        self,
        run_id: str,
        *,
        pipeline_version: str,
        model_key: str,
        pos_mappings: Mapping[str, str] | None = None,
        entity_type_mappings: Mapping[str, str | None] | None = None,
    ) -> None:
        "登记 run 实际使用的 LTP 管线/模型合同"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).ensure_ltp_contract(
                run_id,
                pipeline_version=pipeline_version,
                model_key=model_key,
                pos_mappings=pos_mappings,
                entity_type_mappings=entity_type_mappings,
            ),
            read_only=False,
        )

    def ensure_phrase_contract(
        self, run_id: str, *, lexicon_key: str | None, contract_version: str = FIXED_CONTRACT_VERSION
    ) -> None:
        "登记 run 的固定短语词表来源与计量合同版本（运行内唯一来源）"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).ensure_phrase_contract(
                run_id, lexicon_key=lexicon_key, contract_version=contract_version
            ),
            read_only=False,
        )

    def fetch_run_contract(self, run_id: str) -> NamedRecord | None:
        "读取 run 的语言相关合同列（LTP/短语/w2v 全部在 analysis_runs 一行）"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).fetch_run_contract(run_id), read_only=True
        )

    def save_batch(self, run_id: str, features, entities, phrases, paragraph_ids, *, clear_first: bool):
        "词元、弧、实体、短语及完成标记按批整体提交"

        def operation(session):
            repository = _LinguisticRepository(session)
            repository.insert_linguistic_features(run_id, features, clear_first=clear_first)
            repository.insert_entities(run_id, entities, clear_first=clear_first)
            repository.insert_phrase_hits(run_id, phrases, clear_first=clear_first)
            return repository.mark_phrase_completed(run_id, paragraph_ids)

        return self._runner.run(operation)

    def apply_mneg(self, rows):
        "保存正式语言阶段计算的情绪计数，不接受 SQL 表达式"
        from src.storage.repositories.queries.workflows_linguistic import workflows_linguistic_apply_mneg_correction_1

        return self._runner.run(lambda session: workflows_linguistic_apply_mneg_correction_1(session, rows))

    def insert_linguistic_features(
        self, run_id: str, rows: Sequence[dict[str, Any]], *, clear_first: bool = True
    ) -> int:
        "先清后插写入 run 的逐段语言结构（冻结结构）"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).insert_linguistic_features(
                run_id, rows, clear_first=clear_first
            ),
            read_only=False,
        )

    def has_linguistic_features(self, run_id: str) -> bool:
        "该 run 是否存在语言完成事实（零词元段落同样计入已完成）"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).has_linguistic_features(run_id), read_only=True
        )

    def fetch_linguistic_sources(self, run_id: str) -> dict[str, Any]:
        "按 3NF 前读取形状返回段落语言结构投影行"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).fetch_linguistic_sources(run_id), read_only=True
        )

    def insert_boundary_scores(self, run_id: str, rows: Sequence[tuple[int, float, float]]) -> int:
        "回写段落级边界监督观测（boundary_pos/neg_score_sum，paragraph_metrics 列）"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).insert_boundary_scores(run_id, rows), read_only=False
        )

    def insert_entities(self, run_id: str, rows: Sequence[dict[str, Any]], *, clear_first: bool = True) -> int:
        "先清后插写入 run 的实体候选区间（LTP NER，非图谱事实）"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).insert_entities(run_id, rows, clear_first=clear_first),
            read_only=False,
        )

    def fetch_entities(self, run_id: str) -> Sequence[SimpleNamespace]:
        "实体候选投影：词面按原文切片，归一类型按版本化代码合同"
        return self._runner.run(lambda _session: _LinguisticRepository(_session).fetch_entities(run_id), read_only=True)

    def insert_phrase_hits(self, run_id: str, rows: Sequence[dict[str, Any]], *, clear_first: bool = True) -> int:
        "先清后插写入 run 的固定短语命中区间"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).insert_phrase_hits(run_id, rows, clear_first=clear_first),
            read_only=False,
        )

    def mark_phrase_completed(self, run_id: str, paragraph_ids: Sequence[int]) -> int:
        "把指定段落的 phrase_completed_at 置为真实完成时间（含零命中的段落）"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).mark_phrase_completed(run_id, paragraph_ids),
            read_only=False,
        )

    def fetch_phrase_hits(self, run_id: str) -> Sequence[SimpleNamespace]:
        "短语命中投影：词面按原文切片，is_metric_hit 由运行固定短语合同投影"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).fetch_phrase_hits(run_id), read_only=True
        )

    def has_phrase_hits(self, run_id: str) -> bool:
        "run 是否存在短语完成事实（phrase_completed_at 非空）"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).has_phrase_hits(run_id), read_only=True
        )

    def insert_word2vec_model_run(self, run_id: str, row: dict[str, Any]) -> None:
        "把本次 Word2Vec 实际构建写入 analysis_runs 的 w2v_* 具名列"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).insert_word2vec_model_run(run_id, row), read_only=False
        )

    def fetch_word2vec_model_run(self, run_id: str) -> SimpleNamespace | None:
        "读取 run 的 Word2Vec 实际构建列（属性名保持原契约面）"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).fetch_word2vec_model_run(run_id), read_only=True
        )

    def insert_pos_embeddings(self, run_id: str, rows: Sequence[dict[str, Any]]) -> int:
        "先清后插写入 run 的词性聚合向量（paragraph_features 的 pos_vector 行）"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).insert_pos_embeddings(run_id, rows), read_only=False
        )

    def fetch_pos_embedding_coverage(self, run_id: str, pos_mappings: Mapping[str, str]) -> Sequence[SimpleNamespace]:
        "按词性分组返回覆盖率分子分母（分母由正式词元 × 版本分组投影）"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).fetch_pos_embedding_coverage(run_id, pos_mappings),
            read_only=True,
        )

    def fetch_weighted_pos_embeddings(self, run_id: str) -> Sequence[NamedRecord]:
        "在数据库内汇总词性向量，避免传输所有段落的高维向量"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).fetch_weighted_pos_embeddings(run_id), read_only=True
        )

    def fetch_semantic_vectors(self, run_id: str) -> dict[int, list[float]]:
        "读取 run 的段落语义向量（feature_code='semantic_vector'，NULL 略过）"
        return self._runner.run(
            lambda _session: _LinguisticRepository(_session).fetch_semantic_vectors(run_id), read_only=True
        )


@plain_inputs
class ForestAccess:
    "绑定一个内部事务的数据访问实现"

    def __init__(self, runner):
        self._runner = runner

    def fetch_chapters(self, run_id: str):
        "Forest 数据访问"
        return self._runner.run(lambda _session: _EventForestRecords(_session).fetch_chapters(run_id), read_only=True)

    def fetch_saved_outputs(self, run_id: str):
        "本 run 已正式保存的章节标注：行存在即保存事实，章号从产物行取得"
        return self._runner.run(
            lambda _session: _EventForestRecords(_session).fetch_saved_outputs(run_id), read_only=True
        )

    def fetch_nodes(self, run_id: str, max_chapter_order: int):
        "本 run 在阅读截点内的章级声明，按章序与声明身份稳定排序"
        return self._runner.run(
            lambda _session: _EventForestRecords(_session).fetch_nodes(run_id, max_chapter_order), read_only=True
        )

    def fetch_outputs(self, annotation_ids: set[str]):
        "Forest 数据访问"
        return self._runner.run(
            lambda _session: _EventForestRecords(_session).fetch_outputs(annotation_ids), read_only=True
        )

    def fetch_causal_edges(self, run_id: str, chapter_ids: set[int], *, include_inactive: bool = False):
        "Forest 数据访问"
        return self._runner.run(
            lambda _session: _EventForestRecords(_session).fetch_causal_edges(
                run_id, chapter_ids, include_inactive=include_inactive
            ),
            read_only=True,
        )

    def fetch_foreshadow_roots(self, run_id: str, chapter_ids: set[int]):
        "Forest 数据访问"
        return self._runner.run(
            lambda _session: _EventForestRecords(_session).fetch_foreshadow_roots(run_id, chapter_ids), read_only=True
        )

    def fetch_foreshadow_edges(self, run_id: str):
        "伏笔语义链路：来源/目标都必须是完整事件，声明身份不回填冒充"
        return self._runner.run(
            lambda _session: _EventForestRecords(_session).fetch_foreshadow_edges(run_id), read_only=True
        )
