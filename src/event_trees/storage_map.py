"""event_trees 与冻结 35 表结构之间的读写映射（2026-10-16 全库 3NF 改造）

本模块只做结构映射，不含业务规则：

- 运行归属投影：诊断 work 经整轮会话（executions 的 session 形状）取得运行，
  标注 work 直接带 annotation_run_id，二者不互相冒充
- 证据读写：source_evidence 的九个所有者列恰一，读回按 ordinal 还原原文引用，
  哈希由不可变原文切片重算
- 声明/完整事件读取：声明经 record→标注执行→work 取得运行归属；完整事件经
  真实生产者执行取得；当前阶段是 MAX(stage_index)，不由时间或章号猜
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from src.storage.models import (
    Chapter,
    ChapterAnnotation,
    CompleteEvent,
    EventDeclaration,
    EventRevision,
    Execution,
    Paragraph,
    SourceEvidence,
    WorkItem,
)
from src.utils.identity import text_digest


def run_execution_ids(run_id: str) -> Select:
    """本 run 的真实执行：标注 work 直接带 run，诊断 work 经整轮会话取得运行"""
    diagnosis_sessions = select(Execution.execution_id).where(Execution.session_run_id == run_id)
    return (
        select(Execution.execution_id)
        .join(WorkItem, WorkItem.work_id == Execution.work_id)
        .where(
            or_(
                WorkItem.annotation_run_id == run_id,
                WorkItem.diagnosis_session_id.in_(diagnosis_sessions),
            )
        )
    )


def run_declaration_ids(session: Session, run_id: str) -> set[str]:
    """本 run 的章级声明：记录→标注执行→标注 work 取得运行归属"""
    stmt = (
        select(EventDeclaration.declaration_id)
        .join(ChapterAnnotation, ChapterAnnotation.record_id == EventDeclaration.record_id)
        .join(Execution, Execution.execution_id == ChapterAnnotation.execution_id)
        .join(WorkItem, WorkItem.work_id == Execution.work_id)
        .where(WorkItem.annotation_run_id == run_id)
    )
    return set(session.scalars(stmt))


def run_events(session: Session, run_id: str) -> dict[str, CompleteEvent]:
    """本 run 的完整事件：经真实生产执行取得运行归属"""
    stmt = select(CompleteEvent).where(CompleteEvent.producer_execution_id.in_(run_execution_ids(run_id)))
    return {row.event_id: row for row in session.scalars(stmt)}


def declaration_sources(
    session: Session, record_ids: set[str]
) -> dict[str, tuple[int | None, int | None]]:
    """声明的来源章节：记录→标注执行→标注 work→chapters，返回 record_id→(章号, 章序)"""
    if not record_ids:
        return {}
    rows = session.execute(
        select(ChapterAnnotation.record_id, WorkItem.annotation_chapter_id, Chapter.sequence)
        .join(Execution, Execution.execution_id == ChapterAnnotation.execution_id)
        .join(WorkItem, WorkItem.work_id == Execution.work_id)
        .join(
            Chapter,
            (Chapter.run_id == WorkItem.annotation_run_id) & (Chapter.chapter_id == WorkItem.annotation_chapter_id),
        )
        .where(ChapterAnnotation.record_id.in_(record_ids))
    ).all()
    return {
        str(record_id): (
            int(chapter_id) if chapter_id is not None else None,
            int(sequence) if sequence is not None else None,
        )
        for record_id, chapter_id, sequence in rows
    }


def declaration_record_source(session: Session, record_id: str) -> tuple[str, str, int, int] | None:
    """声明来源记录的真实上下文：work_id、run_id、章号、章序（不存在返回 None）"""
    row = session.execute(
        select(WorkItem.work_id, WorkItem.annotation_run_id, WorkItem.annotation_chapter_id, Chapter.sequence)
        .join(Execution, Execution.work_id == WorkItem.work_id)
        .join(ChapterAnnotation, ChapterAnnotation.execution_id == Execution.execution_id)
        .join(
            Chapter,
            (Chapter.run_id == WorkItem.annotation_run_id) & (Chapter.chapter_id == WorkItem.annotation_chapter_id),
        )
        .where(ChapterAnnotation.record_id == record_id)
        .limit(1)
    ).first()
    if row is None:
        return None
    return str(row[0]), str(row[1]), int(row[2]), int(row[3])


def dialogue_candidate_rows(session: Session, run_id: str) -> list[dict[str, Any]]:
    """对话候选目录：按章序与候选键稳定排序，正文从所属章节区间投影"""
    from src.storage.models import DialogueRecord

    stmt = (
        select(
            DialogueRecord.dialogue_id,
            DialogueRecord.candidate_key,
            DialogueRecord.start_char,
            DialogueRecord.end_char,
            WorkItem.annotation_chapter_id,
            Chapter.text,
        )
        .join(Execution, Execution.execution_id == DialogueRecord.creation_execution_id)
        .join(WorkItem, WorkItem.work_id == Execution.work_id)
        .join(
            Chapter,
            (Chapter.run_id == WorkItem.annotation_run_id) & (Chapter.chapter_id == WorkItem.annotation_chapter_id),
        )
        .where(WorkItem.annotation_run_id == run_id)
        .order_by(Chapter.sequence, DialogueRecord.candidate_key)
    )
    rows: list[dict[str, Any]] = []
    for dialogue_id, candidate_key, start, end, chapter_id, text in session.execute(stmt):
        start_char, end_char = int(start), int(end)
        rows.append(
            {
                "dialogue_id": str(dialogue_id),
                "candidate_key": str(candidate_key),
                "chapter_id": int(chapter_id),
                "start": start_char,
                "end": end_char,
                "content": (text or "")[start_char:end_char],
            }
        )
    return rows


def dialogue_record_by_candidate(session: Session, run_id: str, candidate_key: str):
    """按候选键定位本 run 的对话记录（经原标注来源取得运行归属）"""
    from src.storage.models import DialogueRecord

    return session.scalars(
        select(DialogueRecord)
        .join(Execution, Execution.execution_id == DialogueRecord.creation_execution_id)
        .join(WorkItem, WorkItem.work_id == Execution.work_id)
        .where(WorkItem.annotation_run_id == run_id, DialogueRecord.candidate_key == candidate_key)
        .limit(1)
    ).first()


def work_of_execution(session: Session, execution_id: str) -> str | None:
    """执行所属 work：session 形状无 work，真实 invocation 才有"""
    return session.scalar(select(Execution.work_id).where(Execution.execution_id == execution_id))


def execution_in_run(session: Session, execution_id: str, run_id: str) -> bool:
    """真实执行的本 run 归属（标注 work 或诊断会话）"""
    return (
        session.scalar(
            select(Execution.execution_id).where(
                Execution.execution_id == execution_id,
                Execution.execution_id.in_(run_execution_ids(run_id)),
            )
        )
        is not None
    )


def annotation_chapter_of_execution(session: Session, execution_id: str) -> tuple[int | None, int | None]:
    """标注执行的来源章：章号与章序从标注 work 与 chapters 取得"""
    work_id = work_of_execution(session, execution_id)
    if work_id is None:
        return None, None
    row = session.execute(
        select(WorkItem.annotation_chapter_id, Chapter.sequence)
        .join(
            Chapter,
            (Chapter.run_id == WorkItem.annotation_run_id) & (Chapter.chapter_id == WorkItem.annotation_chapter_id),
        )
        .where(WorkItem.work_id == work_id)
        .limit(1)
    ).first()
    if row is None:
        return None, None
    return int(row[0]), int(row[1])


def chapter_offsets(session: Session, run_id: str, chapter_ids: set[int]) -> dict[int, int]:
    """章正文全文起点；空正文章节无切片，其段落也不存在证据"""
    if not chapter_ids:
        return {}
    rows = session.scalars(
        select(Chapter).where(
            Chapter.run_id == run_id,
            Chapter.chapter_id.in_(chapter_ids),
            Chapter.char_offset.is_not(None),
        )
    )
    return {int(row.chapter_id): int(row.char_offset) for row in rows if row.char_offset is not None}


def paragraph_rows(session: Session, run_id: str, paragraph_ids: set[int]) -> dict[int, Paragraph]:
    if not paragraph_ids:
        return {}
    rows = session.scalars(
        select(Paragraph).where(Paragraph.run_id == run_id, Paragraph.paragraph_id.in_(paragraph_ids))
    )
    return {int(row.paragraph_id): row for row in rows}


def global_positions(session: Session, run_id: str, paragraph_ids: set[int]) -> dict[int, int]:
    """段落全文起点 = 所属章节正文起点 + 章内起点"""
    paragraphs = paragraph_rows(session, run_id, paragraph_ids)
    offsets = chapter_offsets(session, run_id, {row.chapter_id for row in paragraphs.values()})
    positions: dict[int, int] = {}
    for paragraph_id, row in paragraphs.items():
        if int(row.chapter_id) not in offsets:
            raise ValueError(f"段落所属章节缺少正文起点: paragraph_id={paragraph_id}")
        positions[paragraph_id] = offsets[int(row.chapter_id)] + int(row.local_start_char)
    return positions


def evidence_payloads(session: Session, run_id: str, rows: list[SourceEvidence]) -> list[dict[str, Any]]:
    """证据行按 ordinal 重组为原文引用，哈希由不可变原文切片重算"""
    if not rows:
        return []
    ordered = sorted(rows, key=lambda row: int(row.ordinal))
    paragraphs = paragraph_rows(session, run_id, {int(row.paragraph_id) for row in ordered})
    payloads: list[dict[str, Any]] = []
    for row in ordered:
        paragraph = paragraphs.get(int(row.paragraph_id))
        if paragraph is None:
            raise ValueError(f"证据段落不属于本 run: paragraph_id={row.paragraph_id}")
        start, end = int(row.start_char), int(row.end_char)
        payloads.append(
            {
                "event_id": row.related_complete_event_id,
                "paragraph_id": int(row.paragraph_id),
                "chapter_id": int(paragraph.chapter_id),
                "char_start": start,
                "char_end": end,
                "text_hash": text_digest(paragraph.text[start:end]),
            }
        )
    return payloads


def fetch_evidence(session: Session, owner_column: Any, owner_ids: list[str]) -> dict[str, list[SourceEvidence]]:
    """按所有者列批量读取证据行，返回 owner→有序证据"""
    if not owner_ids:
        return {}
    grouped: dict[str, list[SourceEvidence]] = {}
    for row in session.scalars(
        select(SourceEvidence).where(owner_column.in_(owner_ids)).order_by(SourceEvidence.ordinal)
    ):
        owner_value = getattr(row, owner_column.key)
        grouped.setdefault(str(owner_value), []).append(row)
    return grouped


def _ref_field(ref: Any, name: str, default: Any = None) -> Any:
    """证据引用兼容属性形态（pydantic 模型）与映射形态（贡献 JSON）"""
    if isinstance(ref, dict):
        return ref.get(name, default)
    return getattr(ref, name, default)


def write_evidence_rows(session: Session, owner: dict[str, Any], evidence: list[Any]) -> None:
    """证据逐条按原顺序写入 source_evidence；owner 恰一由目标表 CHECK 保证"""
    for ordinal, ref in enumerate(evidence):
        session.add(
            SourceEvidence(
                evidence_id=str(uuid4()),
                ordinal=ordinal,
                paragraph_id=int(_ref_field(ref, "paragraph_id")),
                start_char=int(_ref_field(ref, "char_start", 0)),
                end_char=int(_ref_field(ref, "char_end")),
                related_complete_event_id=_ref_field(ref, "event_id"),
                **owner,
            )
        )


def conflict_payloads(session: Session, run_id: str) -> list[dict[str, Any]]:
    """本 run 的冲突读取形状：主体类型、逐条陈述及各自证据"""
    from src.storage.models import ConflictClaim, ConflictRecord

    rows = list(
        session.scalars(
            select(ConflictRecord)
            .where(ConflictRecord.producer_execution_id.in_(run_execution_ids(run_id)))
            .order_by(ConflictRecord.conflict_id)
        )
    )
    if not rows:
        return []
    conflict_ids = [row.conflict_id for row in rows]
    claims: dict[str, list[ConflictClaim]] = {}
    for claim_row in session.scalars(
        select(ConflictClaim)
        .where(ConflictClaim.conflict_id.in_(conflict_ids))
        .order_by(ConflictClaim.conflict_id, ConflictClaim.claim_ordinal)
    ):
        claims.setdefault(claim_row.conflict_id, []).append(claim_row)
    claim_evidence = fetch_evidence(
        session, SourceEvidence.claim_id, [row.claim_id for rows_ in claims.values() for row in rows_]
    )
    conflict_evidence = fetch_evidence(session, SourceEvidence.conflict_id, conflict_ids)
    items: list[dict[str, Any]] = []
    for row in rows:
        if row.subject_event_id is not None:
            kind, subject_id = "event", row.subject_event_id
        elif row.subject_declaration_id is not None:
            kind, subject_id = "declaration", row.subject_declaration_id
        else:
            kind, subject_id = "fact", str(row.subject_fact_id)
        items.append(
            {
                "conflict_id": row.conflict_id,
                "subject_kind": kind,
                "subject_id": subject_id,
                "claims": [
                    {
                        "claim": claim.claim_text,
                        "producer_invocation_id": claim.producer_execution_id,
                        "evidence": evidence_payloads(session, run_id, claim_evidence.get(claim.claim_id, [])),
                    }
                    for claim in claims.get(row.conflict_id, [])
                ],
                "reason": row.reason,
                "resolution": "unresolved",
                "producer_invocation_id": row.producer_execution_id,
                "evidence": evidence_payloads(session, run_id, conflict_evidence.get(row.conflict_id, [])),
            }
        )
    return items


def stage_chain(session: Session, event_ids: list[str]) -> dict[str, list[EventRevision]]:
    """事件阶段链：按显式 stage_index 升序读取，链尾为当前阶段"""
    if not event_ids:
        return {}
    grouped: dict[str, list[EventRevision]] = {}
    for row in session.scalars(
        select(EventRevision)
        .where(EventRevision.event_id.in_(event_ids))
        .order_by(EventRevision.event_id, EventRevision.stage_index)
    ):
        grouped.setdefault(row.event_id, []).append(row)
    return grouped


def revision_contents(session: Session, revisions: dict[str, list[EventRevision]]) -> dict[str, dict[str, Any]]:
    """阶段内容：绑定声明取不可变声明正文，独立 origin 取 origin_* 列"""
    all_revisions = [row for rows in revisions.values() for row in rows if row is not None]
    if not all_revisions:
        return {}
    declaration_ids = [row.declaration_id for row in all_revisions if row.declaration_id is not None]
    declarations = {
        row.declaration_id: row
        for row in session.scalars(select(EventDeclaration).where(EventDeclaration.declaration_id.in_(declaration_ids)))
    }
    contents: dict[str, dict[str, Any]] = {}
    for revision in all_revisions:
        if revision.declaration_id is not None:
            declaration = declarations.get(revision.declaration_id)
            if declaration is None:
                raise ValueError(f"阶段绑定的声明不存在: declaration_id={revision.declaration_id}")
            contents[revision.revision_id] = {
                "title": declaration.title,
                "problem": declaration.problem,
                "summary": declaration.summary,
                "event_type": declaration.event_type,
                "status": declaration.status,
                "progress": declaration.progress,
            }
            continue
        if revision.origin_title is None:
            raise ValueError(f"独立阶段缺少 origin 正文: revision_id={revision.revision_id}")
        contents[revision.revision_id] = {
            "title": revision.origin_title,
            "problem": revision.origin_problem,
            "summary": revision.origin_summary,
            "event_type": revision.origin_event_type,
            "status": revision.origin_status,
            "progress": revision.origin_progress,
        }
    return contents
