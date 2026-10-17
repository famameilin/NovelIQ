"""按成功 work 只读聚合章节结果，不生成第二份章级持久化产物

2026-10-16 全库 3NF：旧 annotation_work 与 analysis_outputs 退场后
- 完成判定：复用 AnnotationRepository 的标注 work 读投影（work_items 标注形状
  + 该 work 是否存在 chapter_annotations 正式产物行；state 是派生观察，不新增列）
- 章级结果：从正式关系投影重组（chapter_annotations 正式头与具名指标、
  analysis_assessments 段落情绪、event_declarations/declaration_participants、
  dialogue_records）；不恢复通用 payload JSON 列
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import (
    AnalysisAssessment,
    DeclarationParticipant,
    DialogueRecord,
    EventDeclaration,
    Execution,
)
from src.storage.repositories.annotation import AnnotationRepository
from src.storage.repositories.annotation.rows import AnnotationWorkRow
from src.work.policy import completed_chapters

_ROLE_ORDER = {"solo": 0, "structure": 0, "event": 1, "evidence": 2}
#: 每章段落级情绪标签软下限（与标注合同固定覆盖规则同口径，低于此值随章留痕）
_PARAGRAPH_LABEL_MIN_PER_CHAPTER = 2


@dataclass(frozen=True)
class ChapterAnnotationView:
    """章节标注消费视图：字段名与原 AnalysisOutput 读面一致，kind 固定 chapter_annotation"""

    output_id: str
    run_id: str
    chapter_id: int
    role: str | None
    payload: dict[str, Any]
    created_at: datetime
    work_id: str | None = None
    invocation_id: str | None = None
    kind: str = "chapter_annotation"


def fetch_annotation_work_states(session: Session, run_id: str) -> list[AnnotationWorkRow]:
    """标注 work 完成判定视图；saved 由正式标注记录存在性推导（repository 冻结读面）"""
    return AnnotationRepository(session).fetch_work_records(run_id)


def _paragraph_labels(session: Session, record_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """段落情绪标签：正式落点为 analysis_assessments 的逐段情绪分支（按段号定序投影）"""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record_id, paragraph_id, emotion in session.execute(
        select(AnalysisAssessment.record_id, AnalysisAssessment.paragraph_id, AnalysisAssessment.emotion)
        .where(AnalysisAssessment.record_id.in_(record_ids))
        .order_by(AnalysisAssessment.record_id, AnalysisAssessment.paragraph_id)
    ):
        grouped[str(record_id)].append({"paragraph_id": int(paragraph_id), "emotion": emotion})
    return grouped


def _declaration_projections(session: Session, record_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """章级事件：不可变声明正文 + 参与者（实体名字/类型从实体行读取，不复制）"""
    declarations = list(
        session.scalars(
            select(EventDeclaration)
            .where(EventDeclaration.record_id.in_(record_ids))
            .order_by(EventDeclaration.created_at, EventDeclaration.declaration_id)
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not declarations:
        return grouped
    participants: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in session.scalars(
        select(DeclarationParticipant)
        .where(DeclarationParticipant.declaration_id.in_([item.declaration_id for item in declarations]))
        .order_by(DeclarationParticipant.declaration_id, DeclarationParticipant.participant_ordinal)
    ):
        participants[row.declaration_id].append(
            {
                "entity_id": row.entity_id,
                "role": row.role,
                "narrative_role": row.narrative_role,
                "action": row.action,
                "emotion": row.emotion,
            }
        )
    for declaration in declarations:
        grouped[declaration.record_id].append(
            {
                "declaration_id": declaration.declaration_id,
                "local_key": declaration.local_key,
                "title": declaration.title,
                "problem": declaration.problem,
                "summary": declaration.summary,
                "event_type": declaration.event_type,
                "status": declaration.status,
                "progress": declaration.progress,
                "is_foreshadowing_root": declaration.is_foreshadowing_root,
                "payoff_likelihood": declaration.payoff_likelihood,
                "participants": participants.get(declaration.declaration_id, []),
            }
        )
    return grouped


def _dialogue_projections(session: Session, execution_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """对话：正式定位与当前归因（原文从章节区间读取，不复制正文）"""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in session.scalars(
        select(DialogueRecord)
        .where(DialogueRecord.creation_execution_id.in_(execution_ids))
        .order_by(DialogueRecord.creation_execution_id, DialogueRecord.start_char, DialogueRecord.candidate_key)
    ):
        grouped[row.creation_execution_id].append(
            {
                "dialogue_id": row.dialogue_id,
                "candidate_key": row.candidate_key,
                "start": row.start_char,
                "end": row.end_char,
                "speaker_entity_id": row.speaker_entity_id,
                "tone": row.tone,
                "is_inner_monologue": row.is_inner_monologue,
            }
        )
    return grouped


def _character_observations(session: Session, record_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """人物动态观测：只关联原声明参与者（三态至少一项非空即承载一次观测）"""
    declarations = session.execute(
        select(EventDeclaration.declaration_id, EventDeclaration.record_id).where(
            EventDeclaration.record_id.in_(record_ids)
        )
    ).all()
    if not declarations:
        return {}
    record_by_declaration = {row.declaration_id: row.record_id for row in declarations}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in session.scalars(
        select(DeclarationParticipant)
        .where(DeclarationParticipant.declaration_id.in_(list(record_by_declaration)))
        .order_by(DeclarationParticipant.declaration_id, DeclarationParticipant.participant_ordinal)
    ):
        if row.narrative_role is None and row.action is None and row.emotion is None:
            continue
        grouped[record_by_declaration[row.declaration_id]].append(
            {
                "participant_id": row.participant_id,
                "declaration_id": row.declaration_id,
                "entity_id": row.entity_id,
                "role": row.role,
                "narrative_role": row.narrative_role,
                "action": row.action,
                "emotion": row.emotion,
            }
        )
    return grouped


def _coverage_warnings(label_count: int) -> list[str]:
    """固定覆盖规则投影：低于每章软下限只告警、不阻断"""
    if label_count >= _PARAGRAPH_LABEL_MIN_PER_CHAPTER:
        return []
    return [f"情绪标签覆盖: 仅标注 {label_count} 段（每章应自选 2-3 段）"]


def chapter_annotations(session: Session, run_id: str) -> list[ChapterAnnotationView]:
    """按成功 work 聚合章节结果；只读取正式关系，不写任何行"""
    repository = AnnotationRepository(session)
    records = repository.fetch_saved_outputs(run_id)
    works = repository.fetch_work_records(run_id)
    complete = completed_chapters(works)
    if not records or not complete:
        return []
    groups: dict[int, list[Any]] = defaultdict(list)
    for record in records:
        if record.chapter_id in complete:
            groups[record.chapter_id].append(record)
    sequence = repository.fetch_chapter_sequence_map(run_id)
    record_ids = [record.record_id for record in records]
    execution_work = {
        str(execution_id): (str(work_id) if work_id is not None else None)
        for execution_id, work_id in session.execute(
            select(Execution.execution_id, Execution.work_id).where(
                Execution.execution_id.in_([record.execution_id for record in records])
            )
        )
    }
    labels_by_record = _paragraph_labels(session, record_ids)
    declarations_by_record = _declaration_projections(session, record_ids)
    dialogues_by_execution = _dialogue_projections(session, [record.execution_id for record in records])
    observations_by_record = _character_observations(session, record_ids)
    results: list[ChapterAnnotationView] = []
    for chapter_id, sources in sorted(groups.items(), key=lambda item: sequence.get(item[0], item[0])):
        expected = {work.role for work in works if work.chapter_id == chapter_id}
        if {record.role for record in sources} != expected:
            continue
        metric_index = next(
            (index for index, record in enumerate(sources) if record.role in {"solo", "evidence"}), None
        )
        if metric_index is None:
            continue
        ordered = sorted(sources, key=lambda record: _ROLE_ORDER.get(record.role or "", 99))
        metric = sources[metric_index]
        payload: dict[str, Any] = {
            "metrics": {
                "summary": metric.summary,
                "emotional_valence": metric.emotional_valence,
                "narrative_function": metric.narrative_function,
                "pivot_moment": metric.pivot_moment,
                "cliffhanger": metric.cliffhanger,
                "labels": labels_by_record.get(metric.record_id, []),
            }
        }
        payload["events"] = [
            value for record in ordered for value in declarations_by_record.get(record.record_id, [])
        ]
        payload["dialogues"] = [
            value for record in ordered for value in dialogues_by_execution.get(record.execution_id, [])
        ]
        payload["character_observations"] = [
            value for record in ordered for value in observations_by_record.get(record.record_id, [])
        ]
        payload["paragraph_labels"] = [
            value for record in ordered for value in labels_by_record.get(record.record_id, [])
        ]
        payload["coverage_warnings"] = _coverage_warnings(len(payload["paragraph_labels"]))
        results.append(
            ChapterAnnotationView(
                output_id=metric.record_id,
                run_id=run_id,
                chapter_id=chapter_id,
                role=metric.role,
                payload=payload,
                created_at=metric.created_at,
                work_id=execution_work.get(metric.execution_id),
                invocation_id=metric.execution_id,
            )
        )
    return results


def is_annotate_complete(session: Session, run_id: str) -> bool:
    """2026-08-05 用于按真实章节集合严格判断标注阶段完成状态"""
    expected = AnnotationRepository(session).fetch_chapter_ids(run_id)
    if not expected:
        return False
    actual = {record.chapter_id for record in chapter_annotations(session, run_id)}
    return actual == expected
