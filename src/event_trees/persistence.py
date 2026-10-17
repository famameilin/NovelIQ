"""章级声明候选关系的事务保存与核对，不发布正式事件或结构

2026-10-16 全库 3NF 改造（35 表冻结结构）：章级声明之间的候选关系进入
narrative_links 的语义形状（两端都引用 event_declarations），证据进入
source_evidence 的 narrative_link_id 所有者列。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from src.event_trees import storage_map as smap
from src.event_trees.contributions import EventContribution
from src.fact_graph.evidence import evidence_for
from src.storage.models import (
    Chapter,
    ChapterAnnotation,
    CompleteEvent,
    EventDeclaration,
    EventRevision,
    Execution,
    NarrativeLink,
    SourceEvidence,
    WorkItem,
)


def save_declaration_contribution(session: Any, frozen: EventContribution, annotation_id: str) -> None:
    """调用方持有 run 事务锁，任何端点、版本或证据失败均由同一事务整体回滚"""
    payload = frozen.snapshot()
    run_id = frozen.run_id

    def content(key: str) -> list[dict[str, Any]]:
        return [entry["content"] for entry in payload.get(key, {}).values()]

    def evidence(item: dict[str, Any], record: str) -> list[dict[str, Any]]:
        record = item.get("record", record)
        refs = payload.get("source_anchors", {}).get(record)
        if refs:
            return refs
        result = evidence_for(frozen.paragraphs, item.get("evidence_paragraph_id"))
        if not result:
            raise ValueError(f"record={record} field=evidence actual=[] expected=当前 work 真实段落证据")
        return result

    def declaration(identifier: str) -> EventDeclaration:
        row = session.get(EventDeclaration, identifier)
        if row is None:
            raise ValueError(f"declaration_id={identifier} 未有效保存于本 run")
        source = session.execute(
            select(WorkItem.work_id, ChapterAnnotation.execution_id, Chapter.sequence)
            .join(Execution, Execution.execution_id == ChapterAnnotation.execution_id)
            .join(WorkItem, WorkItem.work_id == Execution.work_id)
            .join(
                Chapter,
                (Chapter.run_id == WorkItem.annotation_run_id) & (Chapter.chapter_id == WorkItem.annotation_chapter_id),
            )
            .where(ChapterAnnotation.record_id == row.record_id, WorkItem.annotation_run_id == run_id)
            .limit(1)
        ).first()
        if source is None:
            raise ValueError(f"declaration_id={identifier} 未有效保存于本 run")
        if int(source[2]) > frozen.chapter_order:
            raise ValueError(f"declaration_id={identifier} 来源章晚于当前 work")
        return row

    for key in ("complete_events", "revisions", "containments", "ownerships", "conflicts", "structures"):
        if payload.get(key):
            raise ValueError(f"标注不得保存诊断产物: {key}")
    for item in content("relations"):
        for side in ("source", "target"):
            if item[f"{side}_kind"] != "declaration":
                raise ValueError("标注关系只能连接声明来源")
            declaration(item[f"{side}_id"])
        session.add(
            NarrativeLink(
                link_id=item["relation_id"],
                producer_execution_id=frozen.invocation_id,
                reason=item["reason"],
                semantic_source_declaration_id=item["source_id"],
                semantic_target_declaration_id=item["target_id"],
                relation_type=item["relation_type"],
                source_operation_local_key=item["source_operation_id"],
            )
        )
        smap.write_evidence_rows(
            session,
            {"narrative_link_id": item["relation_id"]},
            evidence(item, f"event_relation/{item['source_operation_id']}"),
        )
    session.flush()


def check_declaration_contribution(session: Any, frozen: EventContribution) -> bool:
    """保存回执核对不可变贡献，后续合法版本不会使先前 work 的保存回执失效"""
    payload = frozen.snapshot()
    specs = (
        (
            "relations",
            NarrativeLink,
            "relation_id",
            ("relation_type", "reason"),
        ),
    )
    for key, model, id_field, fields in specs:
        for entry in payload.get(key, {}).values():
            item = entry["content"]
            identifier = item[id_field]
            row = session.get(model, identifier)
            if row is None:
                return False
            if (
                row.producer_execution_id != frozen.invocation_id
                or row.semantic_source_declaration_id != item["source_id"]
                or row.semantic_target_declaration_id != item["target_id"]
                or row.source_operation_local_key != item["source_operation_id"]
                or any(getattr(row, field) != item[field] for field in fields)
            ):
                return False
            refs = payload.get("source_anchors", {}).get(item.get("record")) or evidence_for(
                frozen.paragraphs, item["evidence_paragraph_id"]
            )
            stored = smap.fetch_evidence(session, SourceEvidence.narrative_link_id, [identifier])
            if [
                (int(evidence.paragraph_id), int(evidence.start_char), int(evidence.end_char))
                for evidence in stored.get(identifier, [])
            ] != [
                (int(ref["paragraph_id"]), int(ref.get("char_start", 0)), int(ref["char_end"])) for ref in refs
            ]:
                return False
    return True


def discard_declaration_contributions(
    session: Any, run_id: str, work_ids: set[str], declaration_ids: list[str]
) -> None:
    """仅撤销未进入诊断发布的标注贡献，已发布 run 不允许局部改写"""
    from sqlalchemy import delete

    if declaration_ids and session.scalar(
        select(EventRevision.declaration_id)
        .join(CompleteEvent, CompleteEvent.event_id == EventRevision.event_id)
        .where(
            EventRevision.declaration_id.in_(declaration_ids),
            CompleteEvent.producer_execution_id.in_(smap.run_execution_ids(run_id)),
        )
        .limit(1)
    ) is not None:
        raise ValueError("声明已正式发布，必须从原文建立新 run")

    executions = select(Execution.execution_id).join(WorkItem, WorkItem.work_id == Execution.work_id).where(
        WorkItem.work_id.in_(work_ids)
    )
    session.execute(
        delete(NarrativeLink).where(
            NarrativeLink.producer_execution_id.in_(executions),
            NarrativeLink.semantic_source_declaration_id.is_not(None),
        )
    )
    session.flush()
