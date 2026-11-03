"""事件组织的原文、来源与已保存记录读取"""

from __future__ import annotations

from typing import Any

from src.event_trees import storage_map as smap
from src.storage import Storage
from src.storage.records.models import CompleteEventRecord as CompleteEvent
from src.storage.records.models import ParagraphRecord as Paragraph


def _paragraph_rows(session: Storage, run_id: str, paragraph_ids: set[int]) -> dict[int, Paragraph]:
    return smap.paragraph_rows(session, run_id, paragraph_ids)


def _evidence_payloads(session: Storage, run_id: str, rows: list[Any]) -> list[dict[str, Any]]:
    """证据行按 ordinal 重组为原文引用，哈希由不可变原文切片重算"""
    return smap.evidence_payloads(session, run_id, rows)


def _global_positions(session: Storage, run_id: str, paragraph_ids: set[int]) -> dict[int, int]:
    """段落全文起点 = 所属正文起点 + 章内起点"""
    return smap.global_positions(session, run_id, paragraph_ids)


def _run_events(session: Storage, run_id: str) -> dict[str, CompleteEvent]:
    return smap.run_events(session, run_id)


def _run_event_dicts(session: Storage, run_id: str) -> dict[str, dict[str, Any]]:
    """本 run 完整事件的读取形状：身份 + 当前内容 + 整体证据"""
    rows = _run_events(session, run_id)
    if not rows:
        return {}
    event_ids = list(rows)
    evidence = smap.fetch_evidence(session, "complete_event_id", event_ids)
    grouped = smap.evidence_payload_groups(session, run_id, [evidence.get(identifier, []) for identifier in rows])
    participant_rows = list(session.reads.events.list_ordered_participants(event_ids))
    entities = (
        {row.entity_id: row for row in session.reads.graph.list_participant_entities(participant_rows)}
        if participant_rows
        else {}
    )
    result: dict[str, dict[str, Any]] = {}
    positions = _global_positions(session, run_id, {item["paragraph_id"] for payloads in grouped for item in payloads})
    for (event_id, row), payloads in zip(rows.items(), grouped, strict=True):
        if not payloads:
            raise ValueError(f"正式事件缺少整体证据: event_id={event_id}")
        result[event_id] = {
            "event_id": event_id,
            "title": row.title,
            "problem": row.problem,
            "summary": row.summary,
            "event_type": row.event_type,
            "status": row.status,
            "progress": row.progress,
            "from": row.from_chapter_id,
            "to": row.to_chapter_id,
            "is_foreshadowing_root": row.is_foreshadowing_root,
            "participants": [
                {
                    "entity": {
                        "entity_id": item.entity_id,
                        "name": entities[item.entity_id].canonical_name,
                        "entity_type": entities[item.entity_id].entity_type,
                    },
                    "role": item.role,
                    "action": item.action,
                    "emotion": item.emotion,
                    "narrative_role": item.narrative_role,
                }
                for item in participant_rows
                if item.event_id == event_id
            ],
            "first_text_position": min(positions[item["paragraph_id"]] + item["char_start"] for item in payloads),
            "evidence": payloads,
        }
    return result


def _execution_in_run(session: Storage, agent_id: str, run_id: str) -> bool:
    """真实执行的本 run 归属：调用形状直接带 run，整轮会话形状带 session_run"""
    return smap.execution_in_run(session, agent_id, run_id)
