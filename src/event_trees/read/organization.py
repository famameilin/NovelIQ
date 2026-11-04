"正式事件、事件及原文证据的只读投影"

from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.event_trees import storage_map as smap
from src.event_trees.action_order import action_order
from src.event_trees.queues import QueueGraph
from src.event_trees.read.organization_models import (
    EventView,
    ForeshadowingView,
    LinkView,
    OutcomeView,
    RunRequiresRebuildError,
)
from src.storage import Storage
from src.storage.records.models import ChapterAnnotationRecord as ChapterAnnotation
from src.storage.records.models import DiagnosisReportRecord as DiagnosisReport
from src.storage.records.models import NarrativeLinkRecord as NarrativeLink
from src.utils.identity import text_digest


def _event_sort_key(event: EventView) -> tuple[bool, int, str]:
    return (event.first_text_position is None, event.first_text_position or 0, event.event_id)


def organization_status(session: Storage, run_id: str) -> str:
    "诊断报告存在即视为事件组织完成"
    return "ready" if session.reads.diagnosis.find_latest_run_report(run_id) is not None else "pending_diagnosis"


class EventTreeQuery:
    """读取全书完整事件树与各级事件详情"""

    def __init__(self, session: Storage, run_id: str, *, light: bool = False) -> None:
        "light 只加载事件与章节，不建树结构、组织关系与伏笔动作"
        self.session, self.run_id = session, run_id
        self.light = light
        self._loaded = False
        self._structure_links: list[NarrativeLink] = []
        self._structure_evidence: list[list[dict[str, Any]]] | None = None
        self._annotation_event_executions: dict[str, str] = {}
        self._tree_line_names: dict[str, str] = {}

    # ------------------------------------------------------------------
    # 加载与契约校验
    # ------------------------------------------------------------------

    def _load_annotations(self) -> list[ChapterAnnotation]:
        return list(self.session.reads.annotations.list_ordered_run_outputs(self.run_id))

    def _load_report(self) -> DiagnosisReport | None:
        return self.session.reads.diagnosis.find_latest_run_report(self.run_id)

    def _load(self) -> None:
        if self._loaded:
            return
        annotations = self._load_annotations()
        report = self._load_report()
        contract_outputs = bool(annotations) or report is not None
        self.organization_status = organization_status(self.session, self.run_id)
        # 章节/段落基础投影先于事件与事件：事件章号与证据坐标都依赖它
        self.chapters: list[dict[str, Any]] = [
            {"chapter_id": row.chapter_id, "title": row.display_title or row.title, "chapter_order": int(row.sequence)}
            for index, row in enumerate(self.session.reads.text.list_readable_chapters(self.run_id))
        ]
        self.orders: dict[int, int] = {row["chapter_id"]: row["chapter_order"] for row in self.chapters}
        self.events = self._load_events()
        if self.light:
            self.paragraphs: dict[int, Any] = {}
            self._tree_rows = []
            self._tree_titles, self._tree_descriptions, self._tree_line_names = {}, {}, {}
            self._structure_links = []
            self.graph = QueueGraph.from_rows([], [], [])
            self.event_line_ids: list[str] = []
            self._line_members: dict[str, set[str]] = {}
            self.outcomes: dict[str, OutcomeView] = {}
            self.relations: list[LinkView] = []
            self.actions: list[ForeshadowingView] = []
            self._action_rows: list[Any] = []
            if not contract_outputs and self.events:
                raise RunRequiresRebuildError()
            self._validate_events(with_text=False)
            self._loaded = True
            return
        self._tree_rows = list(
            self.session.reads.events.list_execution_trees(smap.run_execution_ids(self.session, self.run_id))
        )
        self._tree_titles = {row.group_id: row.title for row in self._tree_rows}
        self._tree_descriptions = {row.group_id: row.description for row in self._tree_rows}
        self._tree_line_names = {
            row.group_id: line_name
            for row in self._tree_rows
            if (line_name := getattr(row, "line_name", None)) is not None
        }
        self._load_queue_graph()
        self.event_line_ids = (
            [row.group_id for row in self._tree_rows if row.is_event_line] if report is not None else []
        )
        self._line_members = {identifier: set(self.graph.tree_events(identifier)) for identifier in self.event_line_ids}
        line_entries = {
            self.graph.queues[identifier][0] for identifier in self.event_line_ids if self.graph.queues[identifier]
        }
        self.events = {key: replace(event, is_event_line=key in line_entries) for key, event in self.events.items()}
        # 已有事件或事件必须保留正式来源产物
        if not contract_outputs and self.events:
            raise RunRequiresRebuildError()
        self._load_organization()
        self.actions = [self._action_view(row) for row in self._action_rows]
        evidence_groups = [
            *(event.evidence for event in self.events.values()),
            *(row.evidence for row in self.outcomes.values()),
            *(row.evidence for row in self.relations),
            *(row.evidence for row in self.actions),
            *self._structure_evidence_payloads(),
        ]
        paragraph_ids = {
            item["paragraph_id"] for evidence in evidence_groups for item in evidence
            if item.get("paragraph_id") is not None
        }
        self.paragraphs = {}
        ordered_paragraph_ids = sorted(paragraph_ids)
        # 分批读取避免证据数量超过数据库参数上限
        for start in range(0, len(ordered_paragraph_ids), 10000):
            rows = self.session.reads.text.list_passages(ordered_paragraph_ids[start:start + 10000], self.run_id)
            self.paragraphs.update({row.paragraph_id: row for row in rows})
        self._validate_saved_contract()
        self._loaded = True

    def _load_events(self) -> dict[str, EventView]:
        rows = smap.run_events(self.session, self.run_id)
        evidence = smap.fetch_evidence(self.session, "complete_event_id", list(rows))
        participants = self._annotation_event_participants(list(rows))
        sources = smap.annotation_sources(
            self.session, {row.annotation_record_id for row in rows.values() if row.annotation_record_id is not None}
        )
        result: dict[str, EventView] = {}
        identifiers = list(rows)
        payload_groups = smap.evidence_payload_groups(
            self.session, self.run_id, [evidence.get(identifier, []) for identifier in identifiers]
        )
        positions = smap.global_positions(
            self.session,
            self.run_id,
            {ref["paragraph_id"] for payloads in payload_groups for ref in payloads},
        )
        for identifier, refs in zip(identifiers, payload_groups, strict=True):
            row = rows[identifier]
            starts = [positions[ref["paragraph_id"]] + ref["char_start"] for ref in refs]
            ends = [positions[ref["paragraph_id"]] + ref["char_end"] for ref in refs]
            source = sources.get(row.annotation_record_id)
            if row.annotation_record_id is not None and source is None:
                raise ValueError("事件标注来源不属于本运行")
            result[identifier] = EventView(
                event_id=identifier,
                producer_agent_id=row.producer_agent_id,
                local_key=row.local_key,
                reason=row.reason,
                title=row.title,
                problem=row.problem,
                summary=row.summary,
                event_type=row.event_type,
                status=row.status,
                progress=row.progress,
                first_text_position=min(starts, default=None),
                evidence=refs,
                source_agent_id=row.producer_agent_id,
                annotation_record_id=row.annotation_record_id,
                from_chapter_id=row.from_chapter_id,
                to_chapter_id=row.to_chapter_id,
                chapter_id=None if source is None else source.chapter_id,
                chapter_order=None if source is None else source.chapter_order,
                participants=participants[identifier],
                is_foreshadowing_root=row.is_foreshadowing_root,
                payoff_likelihood=row.payoff_likelihood,
                char_start=min(starts, default=0),
                char_end=max(ends, default=0),
            )
        return result

    def _load_queue_graph(self) -> None:
        self._structure_links = list(self.session.reads.events.list_queue_links(self.run_id))
        self._structure_evidence = None
        self.graph = QueueGraph.from_rows(
            self._structure_links, list(self.events), [row.group_id for row in self._tree_rows]
        )

    def _annotation_event_participants(self, source_event_ids: list[str]) -> dict[str, list[dict[str, Any]]]:

        result: dict[str, list[dict[str, Any]]] = {key: [] for key in source_event_ids}
        if not source_event_ids:
            return result
        rows = list(self.session.reads.events.list_participants_by_ordinal(source_event_ids))
        entities = (
            {row.entity_id: row for row in self.session.reads.graph.list_referenced_entities(rows)} if rows else {}
        )
        for row in rows:
            entity = entities.get(row.entity_id)
            result[row.event_id].append(
                {
                    "entity": {
                        "name": entity.canonical_name if entity else row.entity_id,
                        "entity_id": row.entity_id,
                        **({"entity_type": entity.entity_type} if entity else {}),
                    },
                    "role": row.role,
                    "narrative_role": row.narrative_role,
                    "action": row.action,
                    "emotion": row.emotion,
                }
            )
        return result

    def _load_organization(self) -> None:

        producer_executions = smap.run_execution_ids(self.session, self.run_id)
        groups = list(self.session.reads.events.list_execution_groups(producer_executions))
        group_evidence = smap.fetch_evidence(self.session, "narrative_group_id", [row.group_id for row in groups])
        outcome_payloads = smap.evidence_payload_groups(
            self.session, self.run_id, [group_evidence.get(row.group_id, []) for row in groups]
        )
        links = list(self.session.reads.events.list_execution_links(producer_executions))
        link_evidence = smap.fetch_evidence(self.session, "narrative_link_id", [row.link_id for row in links])
        link_payloads = smap.evidence_payload_groups(
            self.session, self.run_id, [link_evidence.get(row.link_id, []) for row in links]
        )
        positions = smap.global_positions(
            self.session,
            self.run_id,
            {ref["paragraph_id"] for payloads in [*outcome_payloads, *link_payloads] for ref in payloads},
        )
        self.outcomes = {
            row.group_id: OutcomeView(
                outcome_id=row.group_id,
                title=row.title,
                description=row.description,
                first_text_position=self._first_payload_position(payloads, positions),
                evidence=payloads,
                producer_agent_id=row.producer_agent_id,
            )
            for row, payloads in zip(groups, outcome_payloads, strict=True)
        }
        self.relations = []
        for row, evidence in zip(links, link_payloads, strict=True):
            if row.semantic_source_event_id is not None and row.semantic_target_event_id is not None:
                self.relations.append(
                    self._link_view(
                        row, "event", row.semantic_source_event_id, "event", row.semantic_target_event_id, evidence
                    )
                )
        self.relations.sort(key=lambda row: row.relation_id)
        self._action_rows = self._load_actions()

    def _link_view(
        self,
        row: NarrativeLink,
        source_kind: str,
        source_id: str,
        target_kind: str,
        target_id: str,
        evidence: list[dict[str, Any]],
    ) -> LinkView:
        return LinkView(
            relation_id=row.link_id,
            source_kind=source_kind,
            source_id=source_id,
            target_kind=target_kind,
            target_id=target_id,
            relation_type=row.relation_type or "",
            reason=row.reason,
            evidence=evidence,
            producer_agent_id=row.producer_agent_id,
            source_operation_id=row.source_operation_local_key,
        )

    def _first_payload_position(self, payloads: list[dict[str, Any]], positions: dict[int, int]) -> int:
        if not payloads:
            return 0
        return min(positions[item["paragraph_id"]] + item["char_start"] for item in payloads)

    def _load_actions(self):
        from src.event_trees.action_order import load_foreshadowing_actions

        return load_foreshadowing_actions(self.session, self.run_id)

    def _action_view(self, row: Any) -> ForeshadowingView:
        if not row.source_event_id:
            raise ValueError("已发布伏笔缺少正式事件身份")
        return ForeshadowingView(
            action_id=row.action_id,
            action_type=row.action_type,
            endpoint_kind="event",
            source_event_id=row.source_event_id,
            target_event_id=row.target_event_id,
            chapter_id=row.chapter_id,
            chapter_order=row.chapter_order,
            source_operation_id=row.source_operation_id,
            evidence=row.evidence,
            operation_order=int(row.operation_order),
            evidence_scope=row.evidence_scope,
        )

    # ------------------------------------------------------------------
    # 契约校验
    # ------------------------------------------------------------------

    def _validate_evidence(self, evidence: list[dict[str, Any]]) -> None:
        """拒绝失效来源，不在 GET 中补造段落、坐标或引文"""
        if not evidence:
            raise ValueError("已保存对象缺少原文证据，需要从原文重建")
        for item in evidence:
            chapter_id = item.get("chapter_id")
            if chapter_id not in self.orders:
                raise ValueError("已保存证据章节不属于当前运行")
            if item.get("paragraph_id") is None:
                continue
            paragraph = self.paragraphs.get(item["paragraph_id"])
            if paragraph is None or paragraph.chapter_id != chapter_id:
                raise ValueError("已保存证据段落不属于来源章节")
            start, end = item.get("char_start", 0), item.get("char_end", len(paragraph.text))
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(paragraph.text):
                raise ValueError("已保存证据字符范围与原文不一致")
            if item.get("text_hash") and item["text_hash"] != text_digest(paragraph.text[start:end]):
                raise ValueError("已保存证据文本校验不一致")

    def _structure_evidence_payloads(self) -> list[list[dict[str, Any]]]:
        if self._structure_evidence is None:
            if not self._structure_links:
                self._structure_evidence = []
            else:
                rows = smap.fetch_evidence(
                    self.session, "narrative_link_id", [row.link_id for row in self._structure_links]
                )
                self._structure_evidence = smap.evidence_payload_groups(
                    self.session, self.run_id, [rows.get(row.link_id, []) for row in self._structure_links]
                )
        return self._structure_evidence

    def _validate_events(self, *, with_text: bool = True) -> None:
        "核验事件正文、章节范围与原文证据"
        for event in self.events.values():
            if not all((event.title, event.problem, event.summary, event.event_type, event.status)):
                raise ValueError("全书事件缺少正式正文")
            if event.from_chapter_id not in self.orders or event.to_chapter_id not in self.orders:
                raise ValueError("事件范围不属于本运行")
            if self.orders[event.from_chapter_id] > self.orders[event.to_chapter_id]:
                raise ValueError("事件起止章节顺序无效")
            if with_text:
                self._validate_evidence(event.evidence)
                continue
            if not event.evidence:
                raise ValueError("已保存对象缺少原文证据，需要从原文重建")
            if any(item.get("chapter_id") not in self.orders for item in event.evidence):
                raise ValueError("已保存证据章节不属于当前运行")

    def _validate_saved_contract(self) -> None:
        "核验正式对象、来源与关系端点"
        self._validate_events()
        for relation in self.relations:
            self._locate("event", relation.source_id)
            self._locate("event", relation.target_id)
        for action in self.actions:
            self._locate("event", action.source_event_id)
            if not self.events[action.source_event_id].is_foreshadowing_root:
                raise ValueError("伏笔动作来源事件缺少埋设标记")
            if action.chapter_id not in self.orders or action.chapter_order != self.orders[action.chapter_id]:
                raise ValueError("伏笔动作缺少有效来源章节")
            if any(item.get("chapter_id") != action.chapter_id for item in action.evidence):
                raise ValueError("伏笔动作证据与实际来源章节不一致")
            if action.target_event_id is not None:
                self._locate("event", action.target_event_id)
        for evidence in [
            *(row.evidence for row in self.outcomes.values()),
            *(row.evidence for row in self.relations),
            *(row.evidence for row in self.actions),
        ]:
            self._validate_evidence(evidence)
        # 成员链要求证据；父子引用不要求，有证据时仍逐条核验来源
        for row, evidence in zip(self._structure_links, self._structure_evidence_payloads(), strict=True):
            if row.member_event_id is not None or evidence:
                self._validate_evidence(evidence)

    # ------------------------------------------------------------------
    # 位置与祖先
    # ------------------------------------------------------------------

    def _ancestry(self, event_id: str) -> list[str]:
        "返回全部真实祖先，不制造唯一祖先路径"
        return self.graph.ancestors(event_id)

    def _first_evidence_chapter(self, evidence: list[dict[str, Any]]) -> int | None:
        chapter_ids = [item["chapter_id"] for item in evidence if item.get("chapter_id") in self.orders]
        return min(chapter_ids, key=lambda chapter_id: self.orders[chapter_id]) if chapter_ids else None

    def _event_entry(self, event: EventView) -> dict[str, Any]:
        chapter_id = self._first_evidence_chapter(event.evidence)
        return {
            "event_id": event.event_id,
            "is_event_line": event.is_event_line,
            "from": event.from_chapter_id,
            "to": event.to_chapter_id,
            "title": event.title,
            "problem": event.problem,
            "summary": event.summary,
            "event_type": event.event_type,
            "status": event.status,
            "first_text_position": event.first_text_position,
            "chapter_id": chapter_id,
            "chapter_order": self.orders.get(chapter_id) if chapter_id is not None else None,
        }

    def _locate(self, kind: str, endpoint_id: str) -> dict[str, Any]:
        if kind != "event" or endpoint_id not in self.events:
            raise ValueError("已保存关系的事件端点不属于本运行")
        return {
            "tree_id": self.graph.event_tree[endpoint_id],
            "tree_position": self.graph.positions[endpoint_id],
            "event_line_ids": [key for key, members in self._line_members.items() if endpoint_id in members],
            "evidence_position": self.events[endpoint_id].first_text_position,
        }

    def _relation_entry(self, relation: LinkView, *, locate: tuple[str, str]) -> dict[str, Any]:
        if relation.source_kind != "event" or relation.target_kind != "event":
            raise ValueError("正式事件关系必须直接引用正式事件")
        kind, endpoint_id = locate
        location = self._locate(kind, endpoint_id)
        return {
            "relation_id": relation.relation_id,
            "source_kind": relation.source_kind,
            "source_id": relation.source_id,
            "target_kind": relation.target_kind,
            "target_id": relation.target_id,
            "relation_type": relation.relation_type,
            "reason": relation.reason,
            "evidence": relation.evidence,
            **location,
            "locator": {
                "target_kind": kind,
                "target_id": endpoint_id,
                "title": self.events[endpoint_id].title,
                **location,
            },
        }

    def _action_entry(self, action: ForeshadowingView) -> dict[str, Any]:
        """动作保留自身原文证据，端点位置按现有事件队列计算"""

        def locator(event_id: str) -> dict[str, Any]:
            return {
                "event_id": event_id,
                "title": self.events[event_id].title,
                **self._locate("event", event_id),
            }

        return {
            "action_id": action.action_id,
            "action_type": action.action_type,
            "endpoint_kind": "event",
            "source_event_id": action.source_event_id,
            "target_event_id": action.target_event_id,
            "source_locator": locator(action.source_event_id),
            "target_locator": locator(action.target_event_id) if action.target_event_id is not None else None,
            "chapter_id": action.chapter_id,
            "chapter_order": action.chapter_order,
            "source_operation_id": action.source_operation_id,
            "operation_order": action.operation_order,
            "evidence": action.evidence,
            "evidence_scope": action.evidence_scope,
        }

    def _counts(self) -> dict[str, int]:
        return {
            "event_lines": len(self.event_line_ids),
            "trees": len(self.graph.queues),
            "tree_references": sum(len(values) for values in self.graph.children.values()),
            "all_events": len(self.events),
            "outcomes": len(self.outcomes),
            "relations": len(self.relations),
            "foreshadowing_actions": len(self.actions),
        }

    def _reference_entries(self) -> list[dict[str, Any]]:
        evidence = self._structure_evidence_payloads()
        return [
            {
                "parent_tree_id": row.parent_tree_id,
                "child_tree_id": row.child_tree_id,
                "reason": row.reason,
                "evidence": refs,
            }
            for row, refs in zip(self._structure_links, evidence, strict=True)
            if row.parent_tree_id is not None
        ]

    def _payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "organization_status": self.organization_status,
            "chapters": self.chapters,
            "counts": self._counts(),
            "event_line_ids": self.event_line_ids,
            "queues": [
                {
                    "tree_id": key,
                    "title": self._tree_titles.get(key, ""),
                    "description": self._tree_descriptions.get(key, ""),
                    "is_event_line": key in self.event_line_ids,
                    "line_name": self._tree_line_names.get(key),
                    "event_ids": list(self.graph.queues[key]),
                }
                for key in self.graph.order
            ],
            "events": [self._event_entry(event) for event in sorted(self.events.values(), key=_event_sort_key)],
            "queue_references": self._reference_entries(),
            "outcomes": [
                {
                    "outcome_id": outcome.outcome_id,
                    "title": outcome.title,
                    "description": outcome.description,
                    "first_text_position": outcome.first_text_position,
                    "evidence": outcome.evidence,
                }
                for outcome in sorted(
                    self.outcomes.values(),
                    key=lambda item: (item.first_text_position is None, item.first_text_position or 0, item.outcome_id),
                )
            ],
            "relations": [
                self._relation_entry(relation, locate=(relation.target_kind, relation.target_id))
                for relation in self.relations
            ],
            "foreshadowing_actions": [self._action_entry(action) for action in sorted(self.actions, key=action_order)],
            "next_cursor": None,
        }

    def fetch(self) -> dict[str, Any]:
        """一次返回全部真实树、成员事件与关系，不截取或重新组织事件"""
        self._load()
        return self._payload()

    def participant_references(self, event_id: str) -> list[dict[str, Any]]:
        "读取事件自身的参与引用，不解释实体身份"
        self._load()
        event = self.events.get(event_id)
        if event is None:
            raise LookupError("NODE_NOT_FOUND")
        return [dict(item, entity=dict(item["entity"])) for item in event.participants]

    def detail(self, node_id: str) -> dict[str, Any]:
        """同结构事件卡：各级完整事件同一 DTO，子事件经父卡逐级访问"""
        self._load()
        event = self.events.get(node_id)
        if event is None:
            raise LookupError("NODE_NOT_FOUND")
        evidence = list(event.evidence)
        characters: dict[str, dict[str, Any]] = {}
        for participant in event.participants:
            entity = participant.get("entity") or {}
            identifier = entity.get("entity_id")
            if entity.get("entity_type") != "character" or identifier is None or identifier in characters:
                continue
            characters[identifier] = {
                "entity_id": identifier,
                "name": entity.get("name"),
                "role": participant.get("role"),
            }
        tree_id = self.graph.event_tree[node_id]

        def brief(key: str) -> dict[str, Any]:
            return {
                "event_id": key,
                "title": self.events[key].title,
                "event_type": self.events[key].event_type,
                "status": self.events[key].status,
            }

        return {
            "kind": "event",
            "event_id": event.event_id,
            "run_id": self.run_id,
            "is_event_line": event.is_event_line,
            "from": event.from_chapter_id,
            "to": event.to_chapter_id,
            "title": event.title,
            "problem": event.problem,
            "summary": event.summary,
            "progress": event.progress,
            "event_type": event.event_type,
            "status": event.status,
            "is_foreshadowing_root": event.is_foreshadowing_root,
            "payoff_likelihood": event.payoff_likelihood,
            "foreshadowing_actions": [
                self._action_entry(action)
                for action in sorted(self.actions, key=action_order)
                if node_id in (action.source_event_id, action.target_event_id)
            ],
            "characters": list(characters.values()),
            "tree_id": tree_id,
            "tree_position": self.graph.positions[node_id],
            "event_line_ids": [key for key, members in self._line_members.items() if node_id in members],
            "direct_parents": [brief(key) for key in self.graph.event_parents(node_id)],
            "direct_children": [brief(key) for key in self.graph.event_children(node_id)],
            "evidence": evidence,
            "evidence_scope": (
                "paragraph"
                if evidence and all(item.get("paragraph_id") is not None for item in evidence)
                else "chapter"
            ),
            "source_chapters": sorted(
                {item["chapter_id"] for item in evidence if item.get("chapter_id") in self.orders},
                key=lambda chapter_id: self.orders[chapter_id],
            ),
            "relations": [
                self._relation_entry(
                    relation,
                    locate=(
                        (relation.target_kind, relation.target_id)
                        if relation.source_kind == "event" and relation.source_id == node_id
                        else (relation.source_kind, relation.source_id)
                    ),
                )
                for relation in self.relations
                if (relation.source_kind == "event" and relation.source_id == node_id)
                or (relation.target_kind == "event" and relation.target_id == node_id)
            ],
        }

    def chapter_detail(self, chapter_id: int, event_id: str) -> dict[str, Any]:
        """读取本章标注事件自身正文、参与者和证据"""
        self._load()
        event = self.events.get(event_id)
        if (
            event is None
            or event.chapter_id != chapter_id
            or event.from_chapter_id != chapter_id
            or event.to_chapter_id != chapter_id
        ):
            raise LookupError("NODE_NOT_FOUND")
        return {
            "run_id": self.run_id,
            "chapter_id": chapter_id,
            "event_id": event_id,
            "from": event.from_chapter_id,
            "to": event.to_chapter_id,
            "title": event.title,
            "problem": event.problem,
            "summary": event.summary,
            "status": event.status,
            "progress": event.progress,
            "event_type": event.event_type,
            "participants": [dict(item, entity=dict(item["entity"])) for item in event.participants],
            "evidence": list(event.evidence),
        }

    def export(self) -> dict[str, Any]:
        """导出全部事件树、真实包含边与各级事件详情"""
        self._load()
        result = self._payload()
        result["details"] = [self.detail(event.event_id) for event in sorted(self.events.values(), key=_event_sort_key)]
        result["complete_events"] = [
            {
                "event_id": event.event_id,
                "from": event.from_chapter_id,
                "to": event.to_chapter_id,
                "title": event.title,
                "problem": event.problem,
                "summary": event.summary,
                "progress": event.progress,
                "status": event.status,
                "event_type": event.event_type,
                "source_agent_id": event.source_agent_id,
                "producer_agent_id": event.producer_agent_id,
                "local_key": event.local_key,
                "evidence": event.evidence,
                "first_text_position": event.first_text_position,
            }
            for event in sorted(self.events.values(), key=_event_sort_key)
        ]
        return result
