"""按正文披露章归并独立变化；窗口和分页只裁剪记录，不裁剪历史状态

2026-10-16 全库 3NF 改造（35 表冻结结构）：
- 贡献事实只读 graph_facts 的封闭形状列，旧 content JSON 不再解析
- 章节、作者 work 与章内角色由真实生产执行→标注 work 投影；独立选章取
  effective_chapter_id，不按当前章替代
- 实体/关系状态按贡献顺序在读取侧折叠（entity_states/relation_states 已退场，
  不写第二份状态缓存；折叠口径与旧 changes 的 field/before/after 一致）
- 原文证据按 source_evidence 的 owner 序号读取，文本哈希从正式原文切片计算
- 伏笔动作使用 event_trees.action_order 的正式读投影（声明绑定事件身份）
"""

from __future__ import annotations

import base64
import json
from collections import Counter
from collections.abc import Sequence
from copy import deepcopy
from typing import Any, cast

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from src.event_trees.action_order import load_foreshadowing_actions
from src.event_trees.read.organization import EventTreeQuery
from src.storage.models import (
    Chapter,
    ChapterAnnotation,
    CompleteEvent,
    DeclarationParticipant,
    EventDeclaration,
    EventRevision,
    Execution,
    FactEntityTag,
    GraphEntity,
    GraphFact,
    GraphRelation,
    Paragraph,
    SourceEvidence,
    WorkItem,
)
from src.utils.identity import stable_uuid, text_digest

DIMENSIONS = ("plot", "character", "relationship", "foreshadowing")

#: 贡献事实的角色顺序（与标注 work 的章内角色合同一致）
ROLE_ORDER = {"solo": 0, "structure": 0, "event": 1, "evidence": 2}

#: 不构成情节变化的字段（首次登记的类型/支持数/主角与代表标记沿用原口径）
SKIPPED_DELTA_FIELDS = frozenset({"entity_type", "support_count", "is_main_character", "is_representative"})
#: 允许以空 before 首次出现的字段（人物动态观测）
FIRST_TIME_DELTA_FIELDS = frozenset({"action", "emotion", "role_function"})


class PlotlineQuery:
    """只消费已保存事实，调用方复用整个任务 completed 的访问规则"""

    def __init__(self, session: Session, run_id: str) -> None:
        self.session, self.run_id = session, run_id
        event_query = EventTreeQuery(session, run_id)
        event_query.fetch()
        self.events = event_query.events
        self.organization_status = event_query.organization_status
        rows = session.scalars(
            select(Chapter)
            .where(Chapter.run_id == run_id, Chapter.text.is_not(None))
            .order_by(Chapter.sequence, Chapter.chapter_id)
        ).all()
        self.chapters: list[dict[str, Any]] = [
            {"chapter_id": row.chapter_id, "order": index + 1, "title": row.display_title or row.title}
            for index, row in enumerate(rows)
        ]
        self.orders: dict[int, int] = {row["chapter_id"]: row["order"] for row in self.chapters}
        self._declaration_events = self._fetch_declaration_event_bindings()

    def _cutoff(self, chapter_id: int | None) -> int:
        if chapter_id is None:
            return 1 if self.chapters else 0
        if chapter_id not in self.orders:
            raise ValueError(f"正文阅读章节不存在: {chapter_id}")
        return self.orders[chapter_id]

    def _fetch_declaration_event_bindings(self) -> dict[str, str]:
        """声明绑定的完整事件：由真实版本的声明分支与真实生产执行投影"""
        statement = (
            select(EventRevision.declaration_id, CompleteEvent.event_id)
            .join(CompleteEvent, CompleteEvent.event_id == EventRevision.event_id)
            .where(
                EventRevision.declaration_id.is_not(None),
                CompleteEvent.producer_execution_id.in_(self._run_execution_ids()),
            )
        )
        return {
            str(declaration_id): str(event_id)
            for declaration_id, event_id in self.session.execute(statement).all()
        }

    def _run_execution_ids(self):
        """本运行真实执行：标注 work 直接带运行，诊断 work 经整轮会话取得运行"""
        diagnosis_sessions = select(Execution.execution_id).where(Execution.session_run_id == self.run_id)
        return (
            select(Execution.execution_id)
            .join(WorkItem, WorkItem.work_id == Execution.work_id)
            .where(
                or_(
                    WorkItem.annotation_run_id == self.run_id,
                    WorkItem.diagnosis_session_id.in_(diagnosis_sessions),
                )
            )
        )

    def _fact_chapter_column(self):
        """事实所属章节：标注 work 已决定的章节优先，独立选章取 effective_chapter_id"""
        producer_work_chapter = (
            select(WorkItem.annotation_chapter_id)
            .join(Execution, Execution.work_id == WorkItem.work_id)
            .where(Execution.execution_id == GraphFact.direct_producer_execution_id)
            .scalar_subquery()
        )
        return func.coalesce(producer_work_chapter, GraphFact.effective_chapter_id)

    def _evidence_by_owner(
        self, owner_column, owner_ids: Sequence[int | str]
    ) -> dict[str, list[dict[str, Any]]]:
        """按所有者读取有序原文证据；所有者身份是 uuid 或图谱事实流水（BIGINT）"""
        if not owner_ids:
            return {}
        statement = (
            select(
                owner_column.label("owner_id"),
                SourceEvidence.ordinal,
                SourceEvidence.paragraph_id,
                SourceEvidence.start_char,
                SourceEvidence.end_char,
                Paragraph.chapter_id,
                func.substr(
                    Paragraph.text,
                    SourceEvidence.start_char + 1,
                    SourceEvidence.end_char - SourceEvidence.start_char,
                ).label("quote"),
            )
            .join(
                Paragraph,
                (Paragraph.run_id == self.run_id) & (Paragraph.paragraph_id == SourceEvidence.paragraph_id),
            )
            .where(owner_column.in_(owner_ids))
            .order_by(owner_column, SourceEvidence.ordinal)
        )
        evidence: dict[str, list[dict[str, Any]]] = {}
        for row in self.session.execute(statement).all():
            evidence.setdefault(str(row.owner_id), []).append(
                {
                    "chapter_id": int(row.chapter_id),
                    "paragraph_id": int(row.paragraph_id),
                    "char_start": int(row.start_char),
                    "char_end": int(row.end_char),
                    "text_hash": text_digest(str(row.quote)),
                }
            )
        return evidence

    def _fetch_facts(self, chapter_ids: list[int]) -> list[dict[str, Any]]:
        """本运行在阅读截点内的贡献事实（实体/关系/人物观测/情节推进四种形状）"""
        from_entity = aliased(GraphEntity)
        to_entity = aliased(GraphEntity)
        chapter_column = self._fact_chapter_column()
        direct_statement = (
            select(
                GraphFact.graph_fact_id,
                chapter_column.label("chapter_id"),
                WorkItem.work_id.label("author_work_id"),
                WorkItem.role.label("role"),
                GraphFact.operation_order,
                GraphFact.entity_id,
                GraphFact.relation_id,
                GraphFact.declaration_id,
                GraphFact.plotline_subject_id,
                GraphFact.plotline_subject_title,
                GraphFact.plotline_description,
                GraphFact.plotline_before,
                GraphFact.plotline_after,
                GraphFact.description_action,
                GraphFact.description_value,
                GraphFact.representative_action,
                GraphFact.representative_value,
                GraphFact.tags_submitted,
                GraphFact.relation_change_kind,
                GraphFact.identity_kind,
                GraphFact.reason,
                GraphEntity.canonical_name.label("entity_name"),
                GraphRelation.relation_type,
                from_entity.canonical_name.label("from_entity"),
                to_entity.canonical_name.label("to_entity"),
            )
            .join(Execution, Execution.execution_id == GraphFact.direct_producer_execution_id)
            .join(WorkItem, WorkItem.work_id == Execution.work_id)
            .outerjoin(GraphEntity, GraphEntity.entity_id == GraphFact.entity_id)
            .outerjoin(GraphRelation, GraphRelation.relation_id == GraphFact.relation_id)
            .outerjoin(from_entity, from_entity.entity_id == GraphRelation.from_entity_id)
            .outerjoin(to_entity, to_entity.entity_id == GraphRelation.to_entity_id)
            .where(
                GraphFact.direct_producer_execution_id.is_not(None),
                # 章号是 run 内小整数：必须同时按本运行的真实生产执行限定，防跨 run 串读
                GraphFact.direct_producer_execution_id.in_(self._run_execution_ids()),
                GraphFact.relation_id.is_not(None) | GraphFact.entity_id.is_not(None)
                | GraphFact.plotline_subject_id.is_not(None),
                chapter_column.in_(chapter_ids),
            )
        )
        participant_statement = (
            select(
                GraphFact.graph_fact_id,
                WorkItem.annotation_chapter_id.label("chapter_id"),
                WorkItem.work_id.label("author_work_id"),
                WorkItem.role.label("role"),
                GraphFact.operation_order,
                GraphFact.declaration_id,
                GraphFact.participant_id,
                DeclarationParticipant.entity_id.label("subject_entity_id"),
                GraphEntity.canonical_name.label("entity_name"),
                DeclarationParticipant.narrative_role,
                DeclarationParticipant.action,
                DeclarationParticipant.emotion,
            )
            .join(DeclarationParticipant, DeclarationParticipant.participant_id == GraphFact.participant_id)
            .join(GraphEntity, GraphEntity.entity_id == DeclarationParticipant.entity_id)
            .join(EventDeclaration, EventDeclaration.declaration_id == DeclarationParticipant.declaration_id)
            .join(ChapterAnnotation, ChapterAnnotation.record_id == EventDeclaration.record_id)
            .join(Execution, Execution.execution_id == ChapterAnnotation.execution_id)
            .join(WorkItem, WorkItem.work_id == Execution.work_id)
            .where(
                GraphFact.participant_id.is_not(None),
                WorkItem.annotation_run_id == self.run_id,
                WorkItem.annotation_chapter_id.in_(chapter_ids),
            )
        )
        facts: list[dict[str, Any]] = []
        for row in self.session.execute(direct_statement).mappings():
            values = dict(row)
            values["shape"] = self._direct_fact_shape(values)
            facts.append(values)
        for row in self.session.execute(participant_statement).mappings():
            values = dict(row)
            values["shape"] = "participant"
            values["subject_entity_id"] = values.get("subject_entity_id")
            facts.append(values)
        fact_ids = [int(fact["graph_fact_id"]) for fact in facts]
        evidence = self._evidence_by_owner(SourceEvidence.graph_fact_id, fact_ids)
        tags = self._fetch_fact_tags(fact_ids)
        for fact in facts:
            fact["evidence"] = evidence.get(str(fact["graph_fact_id"]), [])
            fact["tags"] = tags.get(int(fact["graph_fact_id"]), [])
        facts.sort(
            key=lambda fact: (
                self.orders[fact["chapter_id"]],
                ROLE_ORDER.get(str(fact["role"]), 99),
                str(fact["author_work_id"]),
                int(fact["operation_order"] or 0),
                int(fact["graph_fact_id"]),
            )
        )
        return facts

    def _direct_fact_shape(self, fact: dict[str, Any]) -> str:
        """直接生产者事实的形状：关系 > 情节推进 > 实体（列形状互斥，不存重复 kind）"""
        if fact.get("relation_id") is not None:
            return "relation"
        if fact.get("plotline_subject_id") is not None:
            return "plotline"
        return "entity"

    def _fetch_fact_tags(self, fact_ids: list[int]) -> dict[int, list[str]]:
        if not fact_ids:
            return {}
        statement = (
            select(FactEntityTag.graph_fact_id, FactEntityTag.tag_ordinal, FactEntityTag.tag)
            .where(FactEntityTag.graph_fact_id.in_(fact_ids))
            .order_by(FactEntityTag.graph_fact_id, FactEntityTag.tag_ordinal)
        )
        tags: dict[int, list[str]] = {}
        for row in self.session.execute(statement).all():
            tags.setdefault(int(row.graph_fact_id), []).append(str(row.tag))
        return tags

    def _entity_deltas(self, facts: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
        """按贡献顺序折叠实体状态，产出每个事实的字段 before/after（旧状态缓存列的读投影）

        - 实体形状：description 与代表标记按 omit/set/clear 三态、标签按 tags_submitted 投影
        - 人物观测形状：动作/情绪/叙事功能从声明的参与者行读取，保留贡献顺序
        - 不生成变化的固定规则：同值、内部计数/类型/代表标记更新，以及描述与标签的首次登记
          （首次登记不是剧情推进；行为/情绪/叙事作用允许以空 before 首次出现）
        """
        state: dict[str, dict[str, Any]] = {}
        deltas: dict[int, list[dict[str, Any]]] = {}
        for fact in facts:
            shape = fact["shape"]
            if shape == "entity":
                entity_id = fact.get("entity_id")
                if entity_id is None:
                    continue
                values = self._entity_field_values(fact)
            elif shape == "participant":
                entity_id = fact.get("subject_entity_id")
                if entity_id is None:
                    continue
                values = [
                    ("action", fact.get("action")),
                    ("emotion", fact.get("emotion")),
                    ("role_function", fact.get("narrative_role")),
                ]
            else:
                continue
            current = state.setdefault(str(entity_id), {})
            for field, value in values:
                before = current.get(field)
                if before == value:
                    continue
                if field in SKIPPED_DELTA_FIELDS:
                    continue
                if before is None and field not in FIRST_TIME_DELTA_FIELDS:
                    continue
                current[field] = value
                deltas.setdefault(int(fact["graph_fact_id"]), []).append(
                    {"field": field, "before": before, "after": value}
                )
        return deltas

    def _entity_field_values(self, fact: dict[str, Any]) -> list[tuple[str, Any]]:
        """实体形状的字段值：omit 表示未提交、不产生字段（与 clear 的空值区分）"""
        values: list[tuple[str, Any]] = []
        for field, action, value in (
            ("description", fact.get("description_action"), fact.get("description_value")),
            ("is_representative", fact.get("representative_action"), fact.get("representative_value")),
        ):
            if action is None or action == "omit":
                continue
            values.append((field, value if action == "set" else None))
        if fact.get("tags_submitted"):
            values.append(("tags", list(fact.get("tags") or [])))
        return values

    def _changes(self, cutoff: int, *, display_order: bool = True) -> list[dict[str, Any]]:
        chapter_ids = [key for key, order in self.orders.items() if order <= cutoff]
        facts = self._fetch_facts(chapter_ids)
        deltas = self._entity_deltas(facts)
        changes: list[dict[str, Any]] = []
        relation_states: dict[str, dict[str, Any]] = {}
        for fact in facts:
            shape = fact["shape"]
            fields: list[dict[str, Any]] = []
            action: str | None = None
            # before/after 跨维度形态不同（dict/str/list），循环内统一按 Any 传递
            before: Any = None
            after: Any = None
            if shape in {"entity", "participant"}:
                fields = deltas.get(int(fact["graph_fact_id"]), [])
                if not fields:
                    continue
                dimension = "character"
                subject = fact.get("entity_id") if shape == "entity" else fact.get("subject_entity_id")
                name = fact.get("entity_name")
                before = {item["field"]: item["before"] for item in fields}
                after = {item["field"]: item["after"] for item in fields}
                # 各维度形态不同（实体/关系/情节），title 循环内统一按 Any 传递
                title: Any = str(
                    after.get("action")
                    or "、".join(
                        {"emotion": "情绪", "role_function": "叙事作用"}.get(item["field"], item["field"])
                        for item in fields
                    )
                )
            elif shape == "relation":
                dimension, subject = "relationship", fact["relation_id"]
                name = f"{fact.get('from_entity')} · {fact.get('to_entity')}"
                action = str(fact.get("relation_change_kind") or "assert")
                prior = relation_states.get(str(subject))
                before = deepcopy(prior) if prior is not None else None
                after = {"relation_type": fact.get("relation_type"), "active": action not in {"break", "retract"}}
                relation_states[str(subject)] = deepcopy(after)
                if before == after and action == "assert":
                    continue
                if action != "assert":
                    after["change"] = action
                    after["reason"] = fact.get("reason")
                title = fact.get("reason") or f"{fact.get('relation_type')}：{'首次记录' if before is None else action}"
            else:
                dimension, subject = "plot", fact["plotline_subject_id"]
                event_id: str | None = None
                if fact.get("declaration_id") is not None:
                    if self.organization_status != "ready":
                        continue
                    event_id = self._declaration_events.get(str(fact["declaration_id"]))
                    # 显式引用声明的事实按声明绑定投影正式事件；绑定缺失才是数据不一致
                    if event_id is None:
                        raise ValueError(f"情节推进 {fact['graph_fact_id']} 未绑定正式事件")
                name, title = fact.get("plotline_subject_title"), fact.get("plotline_description")
                before, after = fact.get("plotline_before"), fact.get("plotline_after")
                if before == after:
                    continue
                fact["bound_event_id"] = event_id
            evidence = fact["evidence"]
            scope = "paragraph" if shape == "plotline" else "chapter"
            changes.append(
                self._change(
                    str(fact["graph_fact_id"]),
                    dimension,
                    str(subject),
                    str(name),
                    str(title),
                    fact["chapter_id"],
                    before,
                    after,
                    fields,
                    action,
                    evidence,
                    scope,
                    [str(fact["bound_event_id"])] if shape == "plotline" and fact.get("bound_event_id") else [],
                    [str(fact["graph_fact_id"])],
                )
            )
        actions = load_foreshadowing_actions(self.session, self.run_id) if self.organization_status == "ready" else []
        actions = [row for row in actions if row.chapter_id in chapter_ids]
        # 正式伏笔端点已在发布事务绑定，读取时不再用声明寻找另一个 owner
        visible_events = {
            event_id
            for event_id, row in self.events.items()
            if any(item.get("chapter_id") in chapter_ids for item in row.evidence)
        }
        previous: dict[str, str] = {}
        for action_row in actions:
            root = self.events.get(action_row.root_event_id or "")
            if root is None or (action_row.target_event_id and action_row.target_event_id not in visible_events):
                raise ValueError(f"伏笔动作 {action_row.action_id} 的来源或目标不在阅读截点内")
            before = previous.get(root.event_id)
            after = {"setup": "已埋设", "reinforce": "已强化", "payoff": "疑似回收"}[action_row.action_type]
            previous[root.event_id] = after
            changes.append(
                self._change(
                    action_row.action_id,
                    "foreshadowing",
                    root.event_id,
                    cast(str, root.title),
                    after,
                    cast(int, action_row.chapter_id),
                    before,
                    after,
                    [],
                    action_row.action_type,
                    action_row.evidence,
                    action_row.evidence_scope,
                    list(
                        dict.fromkeys(
                            [root.event_id, *([action_row.target_event_id] if action_row.target_event_id else [])]
                        )
                    ),
                    [],
                )
            )
        # 稳定排序保留同位置动作的归并顺序；章级项仍并列，不生成虚构的章内时间
        if display_order:
            changes.sort(
                key=lambda item: (
                    item["chapter_order"],
                    min(item["anchor_paragraph_ids"], default=2**31),
                )
            )
        return changes

    def _change(
        self,
        source: str,
        dimension: str,
        subject: str,
        name: str,
        title: str,
        chapter: int,
        before: Any,
        after: Any,
        deltas: list[dict[str, Any]],
        action: str | None,
        evidence: list[dict[str, Any]],
        scope: str,
        events: list[str],
        facts: list[str],
    ) -> dict[str, Any]:
        return {
            "plotline_change_id": stable_uuid("plotline", self.run_id, dimension, subject, source),
            "dimension": dimension,
            "subject_id": subject,
            "subject_title": name,
            "title": title,
            "chapter_id": chapter,
            "chapter_order": self.orders[chapter],
            "before": before,
            "after": after,
            "deltas": deltas,
            "action": action,
            "evidence_scope": scope,
            "evidence": evidence,
            "anchor_paragraph_ids": sorted({item["paragraph_id"] for item in evidence if "paragraph_id" in item})
            if scope == "paragraph"
            else [],
            "source_event_ids": events,
            "source_fact_ids": facts,
        }

    def fetch(
        self,
        *,
        through_chapter_id: int | None = None,
        window_start_chapter_id: int | None = None,
        window_end_chapter_id: int | None = None,
        subject_id: str | None = None,
        dimension: str | None = None,
        q: str = "",
        cursor: str | None = None,
        limit: int = 100,
        source_fact_id: str | None = None,
    ) -> dict[str, Any]:
        cutoff = self._cutoff(through_chapter_id)
        start = self._cutoff(window_start_chapter_id)
        end = self._cutoff(window_end_chapter_id) if window_end_chapter_id is not None else cutoff
        if start > end or not 1 <= limit <= 500 or (dimension is not None and dimension not in DIMENSIONS):
            raise ValueError("时间轴窗口、维度或分页大小无效")
        all_changes = self._changes(cutoff, display_order=False)
        states: dict[tuple[str, str], dict[str, Any]] = {}
        for change in all_changes:
            key = (change["dimension"], change["subject_id"])
            old = states.get(key, {}).get("state")
            value = deepcopy(change["after"])
            if change["dimension"] == "character":
                value = {**(old or {}), **value}
            states[key] = {
                **{
                    field: change[field]
                    for field in ("subject_id", "subject_title", "dimension", "chapter_id", "chapter_order")
                },
                "state": value,
            }
        selected = [
            item
            for item in all_changes
            if (not subject_id or item["subject_id"] == subject_id)
            and (not dimension or item["dimension"] == dimension)
            and (
                not q
                or q.casefold()
                in json.dumps(
                    [item["subject_title"], item["title"], item["before"], item["after"]], ensure_ascii=False
                ).casefold()
            )
            and (not source_fact_id or source_fact_id in item["source_fact_ids"])
        ]
        counts = Counter((item["chapter_id"], item["chapter_order"], item["dimension"]) for item in selected)
        selected = [item for item in selected if start <= item["chapter_order"] <= end]
        selected.sort(
            key=lambda item: (
                item["chapter_order"],
                min(item["anchor_paragraph_ids"], default=2**31),
            )
        )
        context = [self.run_id, cutoff, start, end, subject_id, dimension, q, source_fact_id]
        offset = 0
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
                if decoded["query"] != context or not isinstance(decoded["offset"], int) or decoded["offset"] < 0:
                    raise ValueError
                offset = decoded["offset"]
            except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                raise ValueError("分页游标与当前时间轴条件不匹配") from exc
        next_offset = offset + limit
        next_cursor = base64.urlsafe_b64encode(
            json.dumps({"query": context, "offset": next_offset}, ensure_ascii=False).encode()
        ).decode()
        return {
            "run_id": self.run_id,
            "organization_status": self.organization_status,
            "chapters": [
                {**chapter, "title": chapter["title"] if chapter["order"] <= cutoff else f"第 {chapter['order']} 章"}
                for chapter in self.chapters
            ],
            "through_chapter_id": next((c["chapter_id"] for c in self.chapters if c["order"] == cutoff), None),
            "changes": selected[offset:next_offset],
            "states": list(states.values()),
            "subjects": [
                {k: value[k] for k in ("dimension", "subject_id", "subject_title")} for value in states.values()
            ],
            "total": len(selected),
            "next_cursor": next_cursor if next_offset < len(selected) else None,
            "distribution": [
                {"chapter_id": key[0], "chapter_order": key[1], "dimension": key[2], "count": count}
                for key, count in sorted(counts.items())
            ],
        }

    def detail(self, change_id: str, through_chapter_id: int) -> dict[str, Any]:
        cutoff = self._cutoff(through_chapter_id)
        for item in self._changes(cutoff):
            if item["plotline_change_id"] == change_id:
                return item
        if any(item["plotline_change_id"] == change_id for item in self._changes(len(self.chapters))):
            raise LookupError("CHANGE_NOT_VISIBLE")
        raise LookupError("CHANGE_NOT_FOUND")

    def export(self) -> dict[str, Any]:
        last = self.chapters[-1]["chapter_id"] if self.chapters else None
        result = self.fetch(through_chapter_id=last)
        result["changes"] = self._changes(len(self.chapters))
        result["next_cursor"] = None
        return result
