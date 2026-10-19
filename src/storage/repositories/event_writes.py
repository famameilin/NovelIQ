from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as Storage

from src.storage.ids import new_id
from src.storage.records.events import EventSave as EventContribution
from src.storage.repositories.queries import event_trees_trees as _queries


class EventWriter:
    def __init__(self, run_id):
        self.run_id = run_id

    def save_work(self, session: Storage, frozen: EventContribution, annotation_id: str) -> None:
        "只保存章级声明与动作来源，全书事件及其正式端点等待诊断发布"
        from src.storage.models import DeclarationParticipant, EventDeclaration, EventForeshadowingAction, GraphFact
        from src.storage.records.evidence import evidence_for
        from src.storage.repositories import narrative_records as smap

        _queries.event_trees_trees_save_work_1(session, self.run_id)
        contribution = frozen.snapshot()
        record = _queries.event_trees_trees_save_work_2(session, annotation_id)
        if (
            record is None
            or record.agent_id != frozen.agent_id
        ):
            raise ValueError("事件保存必须引用本执行的真实标注记录")
        source = smap.declaration_record_source(session, annotation_id)
        if source is None or source.agent_id != frozen.agent_id or source.run_id != self.run_id:
            raise ValueError("事件保存的标注记录不属于本执行或本 run")
        for declaration_id, node in contribution["nodes"].items():
            content = node["content"]
            paragraph = next(row for row in frozen.paragraphs if row.paragraph_id == content["evidence_paragraph_id"])
            refs = contribution.get("process_evidence", {}).get(declaration_id) or evidence_for(
                frozen.paragraphs, paragraph.paragraph_id
            )
            participants = [
                {**item, "entity": frozen.entities()[str(item["entity"])]} for item in content["participants"]
            ]
            local_key = str(contribution.get("event_local_keys", {}).get(declaration_id) or content["node_id"])
            session.add(
                EventDeclaration(
                    declaration_id=declaration_id,
                    record_id=annotation_id,
                    local_key=local_key[:255],
                    title=content["title"],
                    problem=content["problem"],
                    summary=content["summary"],
                    event_type=content["event_type"],
                    status=content["status"],
                    progress=content["progress"],
                    is_foreshadowing_root=bool(content["is_foreshadow_setup"]),
                    payoff_likelihood=content["payoff_likelihood"],
                )
            )
            session.flush()
            for ordinal, item in enumerate(participants):
                entity = item.get("entity") or {}
                entity_id = str(entity.get("entity_id") or entity.get("name") or "")
                if not entity_id:
                    raise ValueError(f"声明参与者缺少正式实体身份: declaration_id={declaration_id}")
                narrative_role = item.get("narrative_role")
                action = item.get("action")
                emotion = None if item.get("emotion") is None else int(item["emotion"])
                participant_id = new_id()
                session.add(
                    DeclarationParticipant(
                        participant_id=participant_id,
                        declaration_id=declaration_id,
                        participant_ordinal=ordinal,
                        entity_id=entity_id,
                        role=str(item.get("role") or ""),
                        narrative_role=narrative_role,
                        action=action,
                        emotion=emotion,
                    )
                )
                if narrative_role or action or emotion:
                    session.flush()
                    fact = GraphFact(participant_id=participant_id)
                    session.add(fact)
                    session.flush()
                    smap.write_evidence_rows(session, {"graph_fact_id": fact.graph_fact_id}, refs)
            smap.write_evidence_rows(session, {"declaration_id": declaration_id}, refs)
        session.flush()
        for identifier, action in contribution.get("actions", {}).items():
            source_row = _queries.event_trees_trees_save_work_3(session, action)
            if source_row is None or not source_row.is_foreshadowing_root:
                raise ValueError(f"source_declaration_id={action['root_event_id']} 缺少有效伏笔声明")
            for field, endpoint_id in (
                ("source_declaration_id", action["root_event_id"]),
                ("target_declaration_id", action.get("target_event_id")),
            ):
                if endpoint_id is None:
                    continue
                endpoint = _queries.event_trees_trees_save_work_4(session, endpoint_id)
                endpoint_source = (
                    smap.declaration_record_source(session, endpoint.record_id) if endpoint is not None else None
                )
                if endpoint_source is None or endpoint_source.run_id != self.run_id:
                    raise ValueError(f"{field}={endpoint_id} 不属于本运行")
                if endpoint_source.chapter_order > frozen.chapter_order:
                    raise ValueError(f"{field}={endpoint_id} 来源章晚于当前章")
            allowed_paragraphs = {row.paragraph_id for row in frozen.paragraphs}
            if not action["evidence"] or any(
                ref.get("paragraph_id") not in allowed_paragraphs for ref in action["evidence"]
            ):
                raise ValueError("伏笔动作须引用当前work真实原文段落")
            session.add(
                EventForeshadowingAction(
                    action_id=identifier,
                    producer_agent_id=frozen.agent_id,
                    source_operation_local_key=str(action["source_operation_id"])[:128],
                    operation_order=int(action["operation_order"]),
                    action_type=action["action_type"],
                    source_declaration_id=action["root_event_id"],
                    target_declaration_id=action.get("target_event_id"),
                )
            )
            smap.write_evidence_rows(session, {"foreshadow_action_id": identifier}, action["evidence"])
        from src.storage.repositories.declaration_writes import save_declaration_contribution

        save_declaration_contribution(session, frozen, annotation_id)
        session.flush()

    def rebuild_storage(self, session: Any) -> None:
        "章级来源不可变，恢复不折叠或回写正式结构和伏笔状态"
        session.flush()

    def discard_storage(self, session: Any, execution_ids: set[str]) -> None:
        "只撤销本执行尚未进入正式发布的声明、动作与来源候选"
        from sqlalchemy import delete

        from src.storage.models import EventDeclaration, EventForeshadowingAction, GraphFact

        identifiers = list(_queries.event_trees_trees_discard_storage_1(session, execution_ids))
        from src.storage.repositories.declaration_writes import discard_declaration_contributions

        discard_declaration_contributions(session, self.run_id, execution_ids, identifiers)
        session.execute(delete(GraphFact).where(GraphFact.declaration_id.in_(identifiers)))
        session.execute(
            delete(EventForeshadowingAction).where(
                EventForeshadowingAction.producer_agent_id.in_(sorted(execution_ids))
                | EventForeshadowingAction.source_declaration_id.in_(identifiers)
                | EventForeshadowingAction.target_declaration_id.in_(identifiers)
            )
        )
        session.execute(delete(EventDeclaration).where(EventDeclaration.declaration_id.in_(identifiers)))
