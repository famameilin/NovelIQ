"event_trees 与冻结 35 表结构之间的读写映射（全库 3NF 改造）"

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from src.storage.ids import new_id
from src.storage.models import (
    Agent,
    Chapter,
    ChapterAnnotation,
    CompleteEvent,
    DialogueRecord,
    EventDeclaration,
    EventDeclarationBinding,
    Paragraph,
    SourceEvidence,
)
from src.storage.records.values import NamedRecord
from src.utils.identity import text_digest


def run_execution_ids(run_id: str) -> Select:
    "本 run 的真实执行：整轮会话行与直接携带 run 的调用行"
    return select(Agent.id).where(or_(Agent.run_id == run_id, Agent.run_id == run_id))


def run_declaration_ids(session: Session, run_id: str) -> set[str]:
    "本 run 的章级声明：记录自身带运行归属"
    stmt = (
        select(EventDeclaration.declaration_id)
        .join(ChapterAnnotation, ChapterAnnotation.record_id == EventDeclaration.record_id)
        .where(ChapterAnnotation.run_id == run_id)
    )
    return set(session.scalars(stmt))


def run_events(session: Session, run_id: str) -> dict[str, CompleteEvent]:
    "本 run 的完整事件：经真实生产执行取得运行归属"
    stmt = select(CompleteEvent).where(CompleteEvent.producer_agent_id.in_(run_execution_ids(run_id)))
    return {row.event_id: row for row in session.scalars(stmt)}


def declaration_sources(session: Session, record_ids: set[str]) -> dict[str, NamedRecord]:
    "声明的来源章节：记录自身的章归属与 chapters，返回 record_id→(章号, 章序)"
    if not record_ids:
        return {}
    rows = session.execute(
        select(ChapterAnnotation.record_id, ChapterAnnotation.chapter_id, Chapter.sequence)
        .join(
            Chapter,
            (Chapter.run_id == ChapterAnnotation.run_id) & (Chapter.chapter_id == ChapterAnnotation.chapter_id),
        )
        .where(ChapterAnnotation.record_id.in_(record_ids))
    ).all()
    return {
        str(row.record_id): NamedRecord({"chapter_id": row.chapter_id, "chapter_order": row.sequence}) for row in rows
    }


def declaration_record_source(session: Session, record_id: str) -> NamedRecord | None:
    "声明来源记录的真实上下文：执行号、run_id、章号、章序（不存在返回 None）"
    row = session.execute(
        select(ChapterAnnotation.agent_id, ChapterAnnotation.run_id, ChapterAnnotation.chapter_id, Chapter.sequence)
        .join(
            Chapter,
            (Chapter.run_id == ChapterAnnotation.run_id) & (Chapter.chapter_id == ChapterAnnotation.chapter_id),
        )
        .where(ChapterAnnotation.record_id == record_id)
        .limit(1)
    ).first()
    if row is None:
        return None
    return NamedRecord(
        {
            "agent_id": str(row.agent_id),
            "run_id": str(row.run_id),
            "chapter_id": int(row.chapter_id),
            "chapter_order": int(row.sequence),
        }
    )


def dialogue_candidate_rows(session: Session, run_id: str) -> list[dict[str, Any]]:
    "对话候选目录：按章序与候选键稳定排序，正文从所属章节区间投影"
    stmt = (
        select(
            DialogueRecord.dialogue_id,
            DialogueRecord.candidate_key,
            DialogueRecord.start_char,
            DialogueRecord.end_char,
            DialogueRecord.chapter_id,
            Chapter.text,
        )
        .join(
            Chapter,
            (Chapter.run_id == DialogueRecord.run_id) & (Chapter.chapter_id == DialogueRecord.chapter_id),
        )
        .where(DialogueRecord.run_id == run_id)
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
    "按候选键定位本 run 的对话记录（记录自身带运行归属）"
    return session.scalars(
        select(DialogueRecord)
        .where(DialogueRecord.run_id == run_id, DialogueRecord.candidate_key == candidate_key)
        .limit(1)
    ).first()


def execution_in_run(session: Session, agent_id: str, run_id: str) -> bool:
    "真实执行的本 run 归属（调用形状带 run，整轮会话形状带 session_run）"
    return (
        session.scalar(
            select(Agent.id).where(
                Agent.id == agent_id,
                or_(Agent.run_id == run_id, Agent.run_id == run_id),
            )
        )
        is not None
    )


def annotation_chapter_of_execution(session: Session, agent_id: str) -> NamedRecord:
    "标注执行的来源章：章号取执行自身归属列，章序从 chapters 取得"
    row = session.execute(
        select(ChapterAnnotation.chapter_id, Chapter.sequence)
        .join(
            Chapter,
            (Chapter.run_id == ChapterAnnotation.run_id) & (Chapter.chapter_id == ChapterAnnotation.chapter_id),
        )
        .where(ChapterAnnotation.agent_id == agent_id)
        .limit(1)
    ).first()
    if row is None:
        return NamedRecord({"chapter_id": None, "chapter_order": None})
    return NamedRecord({"chapter_id": int(row.chapter_id), "chapter_order": int(row.sequence)})


def chapter_offsets(session: Session, run_id: str, chapter_ids: set[int]) -> dict[int, int]:
    "章正文全文起点；空正文章节无切片，其段落也不存在证据"
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
    "段落全文起点 = 所属章节正文起点 + 章内起点"
    paragraphs = paragraph_rows(session, run_id, paragraph_ids)
    offsets = chapter_offsets(session, run_id, {row.chapter_id for row in paragraphs.values()})
    positions: dict[int, int] = {}
    for paragraph_id, row in paragraphs.items():
        if int(row.chapter_id) not in offsets:
            raise ValueError(f"段落所属章节缺少正文起点: paragraph_id={paragraph_id}")
        positions[paragraph_id] = offsets[int(row.chapter_id)] + int(row.local_start_char)
    return positions


def evidence_payload_groups(
    session: Session, run_id: str, groups: list[list[SourceEvidence]]
) -> list[list[dict[str, Any]]]:
    "批量重组多个所有者的证据行；段落一次读取，返回顺序与输入组一致"
    if not groups:
        return []
    flat = [row for group in groups for row in group]
    if not flat:
        return [[] for _ in groups]
    paragraphs = paragraph_rows(session, run_id, {int(row.paragraph_id) for row in flat})
    result: list[list[dict[str, Any]]] = []
    for group in groups:
        payloads: list[dict[str, Any]] = []
        for row in sorted(group, key=lambda item: int(item.ordinal)):
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
        result.append(payloads)
    return result


def evidence_payloads(session: Session, run_id: str, rows: list[SourceEvidence]) -> list[dict[str, Any]]:
    "证据行按 ordinal 重组为原文引用，哈希由不可变原文切片重算"
    return evidence_payload_groups(session, run_id, [rows])[0]


def fetch_evidence(session: Session, owner_column: Any, owner_ids: list[str]) -> dict[str, list[SourceEvidence]]:
    "按所有者列批量读取证据行，返回 owner→有序证据"
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
    "证据引用兼容属性形态（pydantic 模型）与映射形态（贡献 JSON）"
    if isinstance(ref, dict):
        return ref.get(name, default)
    return getattr(ref, name, default)


def write_evidence_rows(session: Session, owner: dict[str, Any], evidence: list[Any]) -> None:
    "证据逐条按原顺序写入 paragraph_evidence；owner 恰一由目标表 CHECK 保证"
    for ordinal, ref in enumerate(evidence):
        session.add(
            SourceEvidence(
                evidence_id=new_id(),
                ordinal=ordinal,
                paragraph_id=int(_ref_field(ref, "paragraph_id")),
                start_char=int(_ref_field(ref, "char_start", 0)),
                end_char=int(_ref_field(ref, "char_end")),
                related_complete_event_id=_ref_field(ref, "event_id"),
                **owner,
            )
        )


def declaration_bindings(session: Session, event_ids: list[str]) -> dict[str, list[EventDeclarationBinding]]:
    "按完整事件返回全部声明归属"
    grouped: dict[str, list[EventDeclarationBinding]] = {}
    if event_ids:
        for row in session.scalars(
            select(EventDeclarationBinding).where(EventDeclarationBinding.event_id.in_(event_ids))
        ):
            grouped.setdefault(row.event_id, []).append(row)
    return grouped
