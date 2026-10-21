"标注事件、包含关系与证据的事务保存及核对"

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from src.storage.models import (
    ChapterAnnotation,
    CompleteEvent,
    EventForeshadowingAction,
    EventParticipant,
    NarrativeLink,
    SourceEvidence,
)
from src.storage.records.events import EventSave as EventContribution
from src.storage.records.evidence import evidence_for
from src.storage.repositories import narrative_records as smap
from src.storage.repositories.queries import event_trees_persistence as _queries


def save_annotation_event_contribution(session: Any, frozen: EventContribution, annotation_id: str) -> None:
    "调用方持有运行事务锁，端点或证据失败时整体回滚"
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

    def annotation_event(identifier: str) -> CompleteEvent:
        row = _queries.event_trees_persistence_annotation_event_1(session, identifier)
        if row is None:
            raise ValueError(f"event_id={identifier} 未有效保存于本 run")
        source = _queries.event_trees_persistence_annotation_event_2(session, row, run_id)
        if source is None:
            raise ValueError(f"event_id={identifier} 未有效保存于本 run")
        if int(source.sequence) > frozen.chapter_order:
            raise ValueError(f"event_id={identifier} 来源章晚于当前 work")
        return row

    for key in ("complete_events", "ownerships", "structures"):
        if payload.get(key):
            raise ValueError(f"标注不得保存诊断产物: {key}")
    for item in content("containments"):
        for identifier in (item["parent_event_id"], item["child_event_id"]):
            annotation_event(identifier)
        session.add(
            NarrativeLink(
                link_id=item["link_id"],
                producer_agent_id=frozen.agent_id,
                contained_parent_id=item["parent_event_id"],
                contained_child_id=item["child_event_id"],
                reason=item["reason"],
            )
        )
        session.flush()
        smap.write_evidence_rows(session, {"narrative_link_id": item["link_id"]}, evidence(item, item["record"]))
    for item in content("relations"):
        for side in ("source", "target"):
            if item[f"{side}_kind"] != "event":
                raise ValueError("标注关系只能连接事件来源")
            annotation_event(item[f"{side}_id"])
        session.add(
            NarrativeLink(
                link_id=item["relation_id"],
                producer_agent_id=frozen.agent_id,
                reason=item["reason"],
                semantic_source_event_id=item["source_id"],
                semantic_target_event_id=item["target_id"],
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


def check_annotation_event_contribution(session: Any, frozen: EventContribution) -> bool:
    "核对同一生产者的完整事件、参与者、关系、动作与证据"
    payload = frozen.snapshot()
    annotation_id = session.scalar(
        select(ChapterAnnotation.record_id).where(ChapterAnnotation.agent_id == frozen.agent_id)
    )
    owned_events = set(
        session.scalars(select(CompleteEvent.event_id).where(CompleteEvent.producer_agent_id == frozen.agent_id))
    )
    owned_links = set(
        session.scalars(select(NarrativeLink.link_id).where(NarrativeLink.producer_agent_id == frozen.agent_id))
    )
    expected_links = {
        entry["content"][field]
        for key, field in (("relations", "relation_id"), ("containments", "link_id"))
        for entry in payload.get(key, {}).values()
    }
    owned_actions = set(
        session.scalars(
            select(EventForeshadowingAction.action_id).where(
                EventForeshadowingAction.producer_agent_id == frozen.agent_id
            )
        )
    )
    if (
        owned_events != set(payload.get("nodes", {}))
        or owned_links != expected_links
        or owned_actions != set(payload.get("actions", {}))
    ):
        return False
    for event_id, entry in payload.get("nodes", {}).items():
        content = entry["content"]
        refs = payload.get("process_evidence", {}).get(event_id) or evidence_for(
            frozen.paragraphs, content["evidence_paragraph_id"]
        )
        expected = {
            field: content[field]
            for field in (
                "title",
                "problem",
                "summary",
                "event_type",
                "status",
                "progress",
                "from_chapter_id",
                "to_chapter_id",
            )
        }
        expected.update(
            producer_agent_id=frozen.agent_id,
            annotation_record_id=annotation_id,
            local_key=str(payload.get("event_local_keys", {}).get(event_id) or content["node_id"])[:255],
            reason=content.get("reason"),
            is_foreshadowing_root=bool(content["is_foreshadow_setup"]),
            payoff_likelihood=content["payoff_likelihood"],
        )
        participants = list(
            session.scalars(
                select(EventParticipant)
                .where(EventParticipant.event_id == event_id)
                .order_by(EventParticipant.participant_ordinal)
            )
        )
        expected_participants = []
        for ordinal, item in enumerate(content["participants"]):
            entity = frozen.entities()[str(item["entity"])]
            expected_participants.append(
                (
                    ordinal,
                    str(entity.get("entity_id") or entity.get("name") or ""),
                    str(item.get("role") or ""),
                    item.get("narrative_role"),
                    item.get("action"),
                    None if item.get("emotion") is None else int(item["emotion"]),
                )
            )
        if [
            (row.participant_ordinal, row.entity_id, row.role, row.narrative_role, row.action, row.emotion)
            for row in participants
        ] != expected_participants:
            return False
        try:
            smap.assert_event_matches(session, event_id, expected, refs)
        except ValueError:
            return False
    for key, id_field in (("relations", "relation_id"), ("containments", "link_id")):
        for entry in payload.get(key, {}).values():
            item = entry["content"]
            identifier = item[id_field]
            row = session.get(NarrativeLink, identifier)
            expected = {"producer_agent_id": frozen.agent_id, "reason": item["reason"]}
            if key == "relations":
                expected.update(
                    semantic_source_event_id=item["source_id"],
                    semantic_target_event_id=item["target_id"],
                    relation_type=item["relation_type"],
                    source_operation_local_key=item["source_operation_id"],
                )
            else:
                expected.update(contained_parent_id=item["parent_event_id"], contained_child_id=item["child_event_id"])
            if row is None or any(getattr(row, field) != value for field, value in expected.items()):
                return False
            refs = payload.get("source_anchors", {}).get(item.get("record")) or evidence_for(
                frozen.paragraphs, item["evidence_paragraph_id"]
            )
            stored = smap.fetch_evidence(session, SourceEvidence.narrative_link_id, [identifier])
            if [
                (ref.paragraph_id, ref.start_char, ref.end_char, ref.related_complete_event_id)
                for ref in stored.get(identifier, [])
            ] != [
                (ref["paragraph_id"], ref.get("char_start", 0), ref["char_end"], ref.get("event_id")) for ref in refs
            ]:
                return False
    for identifier, item in payload.get("actions", {}).items():
        row = session.get(EventForeshadowingAction, identifier)
        expected = {
            "producer_agent_id": frozen.agent_id,
            "source_operation_local_key": str(item["source_operation_id"])[:128],
            "operation_order": int(item["operation_order"]),
            "action_type": item["action_type"],
            "source_event_id": item["root_event_id"],
            "target_event_id": item.get("target_event_id"),
        }
        if row is None or any(getattr(row, field) != value for field, value in expected.items()):
            return False
        stored_action = smap.fetch_evidence(session, SourceEvidence.foreshadow_action_id, [identifier]).get(
            identifier, []
        )
        if [
            (ref.paragraph_id, ref.start_char, ref.end_char, ref.related_complete_event_id) for ref in stored_action
        ] != [
            (ref["paragraph_id"], ref.get("char_start", 0), ref["char_end"], ref.get("event_id"))
            for ref in item["evidence"]
        ]:
            return False
    return True


def discard_annotation_event_contributions(
    session: Any, run_id: str, execution_ids: set[str], source_event_ids: list[str]
) -> None:
    "仅撤销未进入诊断发布的标注贡献，已发布 run 不允许局部改写"
    from sqlalchemy import delete

    if source_event_ids:
        raise ValueError("已保存事件不可局部改写，须从原文建立新运行")
    session.execute(
        delete(NarrativeLink).where(
            NarrativeLink.producer_agent_id.in_(sorted(execution_ids)),
            NarrativeLink.semantic_source_event_id.is_not(None),
        )
    )
    session.flush()
