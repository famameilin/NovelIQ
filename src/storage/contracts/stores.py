"按职责声明数据访问能力，不导入数据库实现"

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Protocol

from src.config.constants.contracts import FIXED_CONTRACT_VERSION
from src.storage.records.annotation import (
    AnnotationRoleRecord,
    DialogueRecordRow,
    ForeshadowingEdgeRow,
    GraphFactRow,
    SavedAnnotationRecord,
)
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


class RunStore(Protocol):
    "Run 的具名访问合同"

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
        ...

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        "获取运行记录"
        ...

    def get_runs_by_novel(self, novel_id: str) -> list[dict[str, Any]]:
        "获取指定小说的所有运行记录"
        ...

    def request_task_cancellation(self, run_id: str) -> str | None:
        "原子性地把可取消任务推进到 cancelling"
        ...

    def get_by_status(self, status: str) -> list[dict[str, Any]]:
        "按状态查询任务。Args: status；Returns: 任务记录列表"
        ...

    def get_pending_tasks(self) -> list[dict[str, Any]]:
        "获取所有 pending 任务"
        ...

    def claim_pending_run(self, run_id: str, *, worker_id: str, heartbeat_at: datetime | None = None) -> bool:
        "原子性领取一个尚未执行的 pending 任务"
        ...

    def cancel_unclaimed_pending_run(self, run_id: str, *, message: str) -> bool:
        "原子性终结尚未被任何 worker 领取的 pending 任务"
        ...

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
        ...

    def get_run_by_task_id(self, task_id: str) -> dict[str, Any] | None:
        "按 run_id 前缀查询（LIKE 转义 %/_/\\"
        ...

    def delete_run(self, run_id: str) -> bool:
        "按运行范围删除全部 run 级数据，由调用方统一提交"
        ...

    def mark_running_as_failed(self) -> int:
        "启动时把所有 running 任务标记为 failed"
        ...

    def mark_cancelling_as_cancelled(self) -> int:
        "启动时把所有 cancelling 任务收口为 cancelled"
        ...


class ChapterStore(Protocol):
    "Chapter 的具名访问合同"

    def insert_chapters(self, run_id: str, chapters: Sequence[ChapterData]) -> None:
        "批量插入章节目录，插入前先删除该 run_id 的旧数据"
        ...

    def insert_chapter_texts(self, run_id: str, chunks: Sequence[Chunk]) -> None:
        "按章节回填正文切片（chapters.char_offset/text，与目录同键一行）"
        ...

    def fetch_chapters(self, run_id: str) -> Sequence[ChapterRecord]:
        "按顺序读取指定 run 的章节目录"
        ...

    def fetch_chapter_texts(self, run_id: str) -> list[tuple[int, str]]:
        "获取所有有正文章节的文本，按章节 sequence 升序"
        ...

    def fetch_chapter_bodies(self, run_id: str) -> Sequence[NamedRecord]:
        "获取 run 的章节正文行（章序 + 正文起点 + 正文终点投影 + 文本）"
        ...

    def fetch_chapter_counts(self, run_id: str) -> tuple[int, int]:
        "获取有正文章节的数量与总字符数"
        ...

    def fetch_all_chapter_texts(self, run_id: str) -> list[str]:
        "获取指定运行的所有章节正文文本（仅文本）"
        ...

    def count_chapters(self, run_id: str) -> int:
        "统计指定运行的有正文章节数量（空正文章节无正文，不计入）"
        ...

    def has_chapters(self, run_id: str) -> bool:
        "检查指定运行是否有正文数据"
        ...


class ParagraphStore(Protocol):
    "Paragraph 的具名访问合同"

    def insert_paragraphs(self, run_id: str, spans: Sequence[ParagraphSpan]) -> int:
        "先删后插写入 run 的段落行（插入前校验不变量）"
        ...

    def has_paragraphs(self, run_id: str) -> bool:
        "run 是否存在段落行"
        ...

    def count_paragraphs(self, run_id: str) -> int:
        "统计指定 run 的段落行数"
        ...

    def fetch_paragraph_rows(self, run_id: str) -> Sequence[NamedRecord]:
        "读取 run 的全部段落行，按 paragraph_id 升序"
        ...

    def fetch_paragraph_rows_batch(
        self, run_id: str, *, chapter_id: int | None = None, after_id: int | None = None, limit: int | None = 128
    ) -> Sequence[NamedRecord]:
        "按 paragraph_id keyset 游标分批读取段落行"
        ...

    def insert_paragraph_metrics(self, run_id: str, rows: Sequence[ParagraphMetricRow]) -> int:
        "先删后插写入 run 的段落指标行（基础计数与充分统计量；派生观测不随本行写入）"
        ...

    def fetch_paragraph_metrics(self, run_id: str) -> Sequence[NamedRecord]:
        "读取 run 的全部段落指标行，按 paragraph_id 升序"
        ...

    def has_paragraph_metrics(self, run_id: str) -> bool:
        "run 是否存在段落指标行"
        ...

    def fetch_chapter_metric_aggregates(self, run_id: str) -> list[tuple[int, dict[str, float]]]:
        "按章聚合段落指标充分统计量（ 分子/分母守恒；char_count 为正文长度投影）"
        ...

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
        ...

    def fetch_topic_model_run(self, run_id: str) -> TopicModelRunContract | None:
        "读取 run 的 LDA 实际构建行（analysis_runs.lda_* + 合同投影）"
        ...

    def insert_paragraph_topic_inferences(
        self, run_id: str, rows: Sequence[tuple[int, int, int, str, str | None, float | None]]
    ) -> int:
        "先清后插写入 run 的段落推断状态（paragraph_metrics.inference_*，每段一行）"
        ...

    def clear_paragraph_topic_inferences(self, run_id: str) -> None:
        "清空 run 的段落推断状态列（paragraph_metrics.inference_*）"
        ...

    def fetch_topic_inference_total(self, run_id: str) -> int | None:
        "全书主题推断分母：所有段落（每段一行）的 inference_token_count 之和"
        ...

    def fetch_chapter_inference_totals(self, run_id: str) -> Sequence[NamedRecord]:
        "按章节返回推断 token 分母（每段一行， 章节聚合分母）"
        ...

    def fetch_topic_emotion_aggregates(self, run_id: str) -> Sequence[NamedRecord]:
        "主题-情感分子分母：net_density 空值段落在 SQL 层同时排除"
        ...

    def insert_paragraph_topics(self, run_id: str, rows: Sequence[tuple[int, int, float]]) -> int:
        '先清后插写入 run 的段落主题行（同 run 重跑语义是"重新计算"）'
        ...

    def clear_paragraph_topics(self, run_id: str) -> None:
        "清空 run 的段落主题行"
        ...

    def fetch_paragraph_topics_agg(self, run_id: str) -> Sequence[NamedRecord]:
        "全书主题分子：按主题返回 token 加权和（，禁止对段落等权求和）"
        ...

    def fetch_chapter_topic_aggregates(self, run_id: str) -> Sequence[NamedRecord]:
        "章节主题分子：按章节返回主题 token 加权和"
        ...

    def fetch_paragraph_topic_rows(self, run_id: str) -> Sequence[NamedRecord]:
        "段落主题序列数据：段落真实字符位置、章节序列与推断 token 数齐备"
        ...

    def insert_paragraph_curves(self, run_id: str, rows: Sequence[ParagraphCurveRow]) -> int:
        "先删后插写入 run 的段落曲线平滑行（paragraph_features 两类标量行，缺值保持 NULL）"
        ...

    def fetch_paragraph_curves(self, run_id: str) -> Sequence[NamedRecord]:
        "读取 run 的全部段落曲线行（密度/张力为读投影，平滑值取特征行）"
        ...

    def fetch_chapter_tension_scores(self, run_id: str) -> list[tuple[int, float]]:
        "每章张力 = 章内段落 surface_tension 均值（供 timeline/聚合使用）"
        ...

    def has_paragraph_curves(self, run_id: str) -> bool:
        "run 是否存在段落曲线平滑样本行"
        ...


class AnnotationStore(Protocol):
    "Annotation 的具名访问合同"

    def fetch_chapter_sequence_map(self, run_id: str) -> dict[int, int]:
        "Annotation 数据访问"
        ...

    def fetch_chapter_ids(self, run_id: str) -> set[int]:
        "Annotation 数据访问"
        ...

    def fetch_saved_outputs(self, run_id: str) -> list[SavedAnnotationRecord]:
        "本运行已正式保存的章节标注：行存在即保存事实，章号/角色取记录自身列"
        ...

    def fetch_role_records(self, run_id: str) -> list[AnnotationRoleRecord]:
        "本运行的章内标注角色：state 由正式标注记录的存在性表达，执行号取产物行自身"
        ...

    def fetch_entities_by_id(self, run_id: str) -> dict[str, GraphEntityRecord]:
        "Annotation 数据访问"
        ...

    def fetch_dialogue_records(self, run_id: str) -> list[DialogueRecordRow]:
        "本运行对话记录：run/章是创建时自落归属，内容按章节区间精确切片"
        ...

    def fetch_foreshadowing_roots(self, run_id: str, *, ordered: bool = False) -> list[EventDeclarationRecord]:
        "Annotation 数据访问"
        ...

    def fetch_foreshadowing_edges(self, run_id: str, *, ordered: bool = False) -> list[ForeshadowingEdgeRow]:
        "伏笔语义链路读投影；ordered 时按目标事件来源章序排序（无证据章的链路排后）"
        ...

    def fetch_event_records(self, run_id: str, event_ids: set[str]) -> list[EventDeclarationRecord]:
        "Annotation 数据访问"
        ...

    def fetch_foreshadowing_edge_counts(self, run_id: str) -> dict[str, int]:
        "Annotation 数据访问"
        ...

    def fetch_graph_facts(self, run_id: str, *, content_kind: str) -> list[GraphFactRow]:
        "本运行指定形状的正式图贡献事实（旧内容类型名映射到冻结形状列）"
        ...


class GraphStore(Protocol):
    "Graph 的具名访问合同"

    def run_exists(self, run_id: str) -> bool: ...

    def resolve_chapter_boundary(self, run_id: str, *, chapter_id: int | None = None) -> ChapterBoundary | None:
        "用于解析显式章节或当前运行最后章节"
        ...

    def resolve_persisted_boundary(self, run_id: str) -> ChapterBoundary | None:
        "用于构造覆盖全部已提交数据的历史边界（不依赖 annotation record）"
        ...

    def fetch_entity_snapshots(self, boundary: ChapterBoundary) -> list[EntitySnapshotRow]:
        "用于选择目标章节以前最近状态并继承无变化实体"
        ...

    def fetch_relation_snapshots(
        self, boundary: ChapterBoundary, *, active_only: bool = True
    ) -> list[RelationSnapshotRow]:
        "用于选择目标章节以前最近关系状态并过滤活动状态"
        ...

    def fetch_snapshot(self, run_id: str, *, chapter_id: int | None = None) -> GraphSnapshotRow | None:
        "用于返回目标章节边界的实体状态与有效关系"
        ...

    def fetch_changes(
        self, run_id: str, *, chapter_id: int | None = None, offset: int = 0, limit: int | None = 200
    ) -> tuple[list[GraphChangeRow], int]:
        "用于按章节倒序分页返回状态和关系变化"
        ...

    def fetch_latest_entity_rows(self, run_id: str, *, entity_type: str | None = None) -> list[EntitySnapshotRow]:
        "用于读取当前章节边界的实体状态"
        ...

    def fetch_latest_relations(self, run_id: str, *, active_only: bool = True) -> list[RelationSnapshotRow]:
        "用于读取当前章节边界的关系状态"
        ...

    def fetch_relation_history(self, run_id: str) -> list[RelationSnapshotRow]:
        "按章节顺序读取关系历史，共享一次折叠结果，避免逐状态重建全图"
        ...

    def fetch_relation_changes(self, run_id: str, *, limit: int | None = None) -> list[GraphChangeRow]:
        "用于读取诊断时间轴所需的关系变化事实"
        ...

    def count_chapters(self, run_id: str) -> int:
        "用于统计当前运行已提交的章节数量"
        ...


class DiagnosisStore(Protocol):
    "Diagnosis 的具名访问合同"

    def fetch_high_tension_chunks(self, run_id: str, limit: int | None = None) -> list[tuple[int, str, float]]:
        "高张力诊断数据源为正式表面张力读数（ 事实定位段落化）"
        ...

    def fetch_topic_weights(self, run_id: str, top_n: int | None = None) -> list[dict[str, Any]]:
        "Diagnosis 数据访问"
        ...


class StatisticsStore(Protocol):
    "Statistics 的具名访问合同"

    def insert_global_stats(self, run_id: str, stats: Iterable[tuple[str, float | None]]) -> None:
        "插入全局统计数据"
        ...

    def fetch_global_stats_dict(self, run_id: str) -> dict[str, float | None]:
        "获取全局统计数据字典"
        ...

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
        ...

    def has_topic_data(self, run_id: str) -> bool:
        "检查指定运行是否有主题数据"
        ...

    def has_linguistic_data(self, run_id: str) -> bool:
        "检查指定运行是否有语言结构基础数据"
        ...

    def insert_agent_analysis(self, run_id: str, payload: Mapping[str, Any]) -> str:
        "诊断产物追加进分析产物表，返回产物 id"
        ...

    def fetch_agent_analysis(self, run_id: str) -> dict[str, Any] | None:
        "获取最新诊断产物"
        ...

    def fetch_novel_title(self, novel_id: str) -> str | None:
        "获取小说标题"
        ...


class LinguisticStore(Protocol):
    "Linguistic 的具名访问合同"

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
        ...

    def ensure_phrase_contract(
        self, run_id: str, *, lexicon_key: str | None, contract_version: str = FIXED_CONTRACT_VERSION
    ) -> None:
        "登记 run 的固定短语词表来源与计量合同版本（运行内唯一来源）"
        ...

    def fetch_run_contract(self, run_id: str) -> NamedRecord | None:
        "读取 run 的语言相关合同列（LTP/短语/w2v 全部在 analysis_runs 一行）"
        ...

    def insert_linguistic_features(
        self, run_id: str, rows: Sequence[dict[str, Any]], *, clear_first: bool = True
    ) -> int:
        "先清后插写入 run 的逐段语言结构（冻结结构）"
        ...

    def has_linguistic_features(self, run_id: str) -> bool:
        "该 run 是否存在语言完成事实（零词元段落同样计入已完成）"
        ...

    def fetch_linguistic_sources(self, run_id: str) -> dict[str, Any]:
        "按 3NF 前读取形状返回段落语言结构投影行"
        ...

    def insert_boundary_scores(self, run_id: str, rows: Sequence[tuple[int, float, float]]) -> int:
        "回写段落级边界监督观测（boundary_pos/neg_score_sum，paragraph_metrics 列）"
        ...

    def insert_entities(self, run_id: str, rows: Sequence[dict[str, Any]], *, clear_first: bool = True) -> int:
        "先清后插写入 run 的实体候选区间（LTP NER，非图谱事实）"
        ...

    def fetch_entities(self, run_id: str) -> Sequence[SimpleNamespace]:
        "实体候选投影：词面按原文切片，归一类型按版本化代码合同"
        ...

    def insert_phrase_hits(self, run_id: str, rows: Sequence[dict[str, Any]], *, clear_first: bool = True) -> int:
        "先清后插写入 run 的固定短语命中区间"
        ...

    def mark_phrase_completed(self, run_id: str, paragraph_ids: Sequence[int]) -> int:
        "把指定段落的 phrase_completed_at 置为真实完成时间（含零命中的段落）"
        ...

    def fetch_phrase_hits(self, run_id: str) -> Sequence[SimpleNamespace]:
        "短语命中投影：词面按原文切片，is_metric_hit 由运行固定短语合同投影"
        ...

    def has_phrase_hits(self, run_id: str) -> bool:
        "run 是否存在短语完成事实（phrase_completed_at 非空）"
        ...

    def insert_word2vec_model_run(self, run_id: str, row: dict[str, Any]) -> None:
        "把本次 Word2Vec 实际构建写入 analysis_runs 的 w2v_* 具名列"
        ...

    def fetch_word2vec_model_run(self, run_id: str) -> SimpleNamespace | None:
        "读取 run 的 Word2Vec 实际构建列（属性名保持原契约面）"
        ...

    def insert_pos_embeddings(self, run_id: str, rows: Sequence[dict[str, Any]]) -> int:
        "先清后插写入 run 的词性聚合向量（paragraph_features 的 pos_vector 行）"
        ...

    def fetch_pos_embedding_coverage(self, run_id: str, pos_mappings: Mapping[str, str]) -> Sequence[SimpleNamespace]:
        "按词性分组返回覆盖率分子分母（分母由正式词元 × 版本分组投影）"
        ...

    def fetch_weighted_pos_embeddings(self, run_id: str) -> Sequence[NamedRecord]:
        "在数据库内汇总词性向量，避免传输所有段落的高维向量"
        ...

    def fetch_semantic_vectors(self, run_id: str) -> dict[int, list[float]]:
        "读取 run 的段落语义向量（feature_code='semantic_vector'，NULL 略过）"
        ...


class ForestStore(Protocol):
    "Forest 的具名访问合同"

    def fetch_chapters(self, run_id: str):
        "Forest 数据访问"
        ...

    def fetch_saved_outputs(self, run_id: str):
        "本 run 已正式保存的章节标注：行存在即保存事实，章号从产物行取得"
        ...

    def fetch_nodes(self, run_id: str, max_chapter_order: int):
        "本 run 在阅读截点内的章级声明，按章序与声明身份稳定排序"
        ...

    def fetch_outputs(self, annotation_ids: set[str]):
        "Forest 数据访问"
        ...

    def fetch_causal_edges(self, run_id: str, chapter_ids: set[int], *, include_inactive: bool = False):
        "Forest 数据访问"
        ...

    def fetch_foreshadow_roots(self, run_id: str, chapter_ids: set[int]):
        "Forest 数据访问"
        ...

    def fetch_foreshadow_edges(self, run_id: str):
        "伏笔语义链路：来源/目标都必须是完整事件，声明身份不回填冒充"
        ...
