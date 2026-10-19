"完整事件组织草稿、原文绑定与正式产出保存"

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from src.event_trees import storage_map as smap
from src.fact_graph.outputs import SourceReference
from src.storage import Storage, new_id
from src.storage.records.models import CompleteEventRecord as CompleteEvent
from src.storage.records.models import ParagraphRecord as Paragraph
from src.utils.identity import text_digest


def _validate_narrative_description(value: str) -> str:
    if sum(not unicodedata.category(char).startswith("P") for char in value) > 20:
        raise ValueError("目标或说明最多20字，不计算标点，请精简后重写并重新提交")
    return value


def _validate_narrative_title(value: str) -> str:
    if sum(not unicodedata.category(char).startswith("P") for char in value) > 6:
        raise ValueError("标题最多6字，不计算标点，请精简后重写并重新提交")
    return value


NarrativeTitle = Annotated[
    str,
    Field(min_length=1, description="单一精练标题，最多6字；不计算Unicode标点，其余字符逐字计数；超限须重写"),
    AfterValidator(_validate_narrative_title),
]
NarrativeDescription = Annotated[
    str,
    Field(min_length=1, description="一句目标或结果说明，最多20字；不计算Unicode标点，其余字符逐字计数；超限须重写"),
    AfterValidator(_validate_narrative_description),
]


def snapshot_digest(payload: Any) -> str:
    """稳定摘要只绑定业务内容，不包含审计或容量租约"""
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def record_payloads(records: Any) -> list[dict[str, Any]]:
    """无序候选集合以内容排序，跨工作恢复顺序不改变核对结果"""
    return sorted((item.model_dump(mode="json") for item in records), key=snapshot_digest)


class CandidateConflict(ValueError):
    """可定位的候选冲突只返回真实生产者，不能重开无关会话"""

    def __init__(self, message: str, producer_agent_ids: list[str]) -> None:
        self.producer_agent_ids = tuple(sorted(set(producer_agent_ids)))
        super().__init__(message)


class OrganizationEvidence(BaseModel):
    """工具只接受真实段号与逐字引文，坐标和哈希由服务端绑定"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    paragraph_id: int = Field(ge=0)
    quote: str | None = Field(default=None, min_length=1)
    occurrence: int = Field(default=1, ge=1)
    event_id: str | None = Field(default=None, min_length=1)


class BoundOrganizationEvidence(SourceReference):
    """正式证据保留可选的完整事件引用与已绑定原文位置"""

    event_id: str | None = None


class OrganizationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence: list[BoundOrganizationEvidence] = Field(min_length=1, max_length=100)
    producer_agent_id: str = ""


class NarrativeArcDraft(OrganizationRecord):
    arc_id: str
    parent_arc_id: str | None = None
    kind: Literal["main", "subplot"]
    title: NarrativeTitle
    objective: NarrativeDescription
    role: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class EventArcLinkDraft(OrganizationRecord):
    event_id: str
    arc_id: str
    role: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class EventOutcomeDraft(OrganizationRecord):
    outcome_id: str
    title: NarrativeTitle
    description: NarrativeDescription
    first_text_position: int = Field(ge=0)


class EventOutcomeLinkDraft(OrganizationRecord):
    event_id: str
    outcome_id: str
    reason: str = Field(min_length=1)


class EventReviewDraft(BaseModel):
    """诊断产物的覆盖审计，不制造无原文依据的线或结果关联"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: str
    reason: str = Field(min_length=1)
    snapshot_hash: str = Field(min_length=1)
    producer_agent_id: str


class CompleteEventDraft(OrganizationRecord):
    """诊断待保存的完整事件；直接过程与子事件作为同一笔原子输入"""

    event_id: str
    local_key: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1)
    problem: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    status: Literal["ongoing", "resolved"]
    progress: str | None = None
    declaration_ids: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    source_hashes: dict[str, str] = Field(default_factory=dict)
    first_text_position: int = Field(ge=0)


class ContainmentDraft(OrganizationRecord):
    parent_event_id: str
    child_event_id: str
    reason: str = Field(min_length=1)


class DeclarationReviewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    declaration_id: str
    source_hash: str
    reason: str = Field(min_length=1)
    producer_agent_id: str


class DeclarationComparisonDraft(OrganizationRecord):
    source_declaration_id: str
    target_declaration_ids: list[str] = Field(min_length=1)
    disposition: Literal["same_event", "independent", "related"]
    reason: str = Field(min_length=1)


class StructureReviewDraft(OrganizationRecord):
    source_event_id: str
    target_event_id: str
    disposition: Literal["contains", "part_of", "related", "independent"]
    reason: str = Field(min_length=1)
    snapshot_hash: str


class RelationDraft(OrganizationRecord):
    relation_id: str
    source_kind: Literal["event"]
    source_id: str
    target_kind: Literal["event"]
    target_id: str
    relation_type: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    source_operation_id: str


class NarrativeOrganization(BaseModel):
    """完整事件的全书组织；章节概要、类型和包含结构保持不可变"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source_agent_id: str | None = None
    events: list[CompleteEventDraft] = Field(default_factory=list)
    relations: list[RelationDraft] = Field(default_factory=list)
    arcs: list[NarrativeArcDraft] = Field(default_factory=list)
    event_arc_links: list[EventArcLinkDraft] = Field(default_factory=list)
    outcomes: list[EventOutcomeDraft] = Field(default_factory=list)
    event_outcome_links: list[EventOutcomeLinkDraft] = Field(default_factory=list)
    reviewed_events: list[EventReviewDraft] = Field(default_factory=list)
    declaration_reviews: list[DeclarationReviewDraft] = Field(default_factory=list)
    declaration_comparisons: list[DeclarationComparisonDraft] = Field(default_factory=list)
    containments: list[ContainmentDraft] = Field(default_factory=list)
    identity_snapshot: str | None = None
    structure_snapshot: str | None = None
    structure_reviews: list[StructureReviewDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_structure(self) -> NarrativeOrganization:
        arcs = {arc.arc_id: arc for arc in self.arcs}
        outcomes = {item.outcome_id for item in self.outcomes}
        for records, keys in (
            (self.events, {item.event_id for item in self.events}),
            (self.relations, {item.relation_id for item in self.relations}),
            (self.arcs, list(arcs)),
            (self.outcomes, list(outcomes)),
            (self.reviewed_events, {item.event_id for item in self.reviewed_events}),
            (self.event_arc_links, {(item.event_id, item.arc_id) for item in self.event_arc_links}),
            (self.event_outcome_links, {(item.event_id, item.outcome_id) for item in self.event_outcome_links}),
        ):
            if len(records) != len(keys):
                raise ValueError("全书组织身份或关联端点重复")
        for arc in self.arcs:
            current: str | None = arc.arc_id
            seen: set[str] = set()
            while current is not None:
                if current not in arcs:
                    raise ValueError(f"父级叙事线不存在: {current}")
                if current in seen:
                    raise ValueError(f"叙事线父级形成环: {current}")
                seen.add(current)
                current = arcs[current].parent_arc_id
        for link in self.event_arc_links:
            if link.arc_id not in arcs:
                raise ValueError(f"叙事线关联端点不存在: {link.arc_id}")
        for outcome_link in self.event_outcome_links:
            if outcome_link.outcome_id not in outcomes:
                raise ValueError(f"结果关联端点不存在: {outcome_link.outcome_id}")
        if outcomes != {link.outcome_id for link in self.event_outcome_links}:
            raise ValueError("独立结果必须具有具体事件贡献关系")
        return self


# ---------------------------------------------------------------------------
# 诊断会话与真实执行的登记（新关系；不恢复 checkpoint）
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 本 run 的声明、完整事件与关系的读取投影
# ---------------------------------------------------------------------------


def run_declaration_ids(session: Storage, run_id: str) -> set[str]:
    """本 run 的章级声明：记录自身携带运行归属"""
    return smap.run_declaration_ids(session, run_id)


def _chapter_offsets(session: Storage, run_id: str, chapter_ids: set[int]) -> dict[int, int]:
    """章正文全文起点；空正文章节无切片，其段落也不存在证据"""
    return smap.chapter_offsets(session, run_id, chapter_ids)


def _paragraph_rows(session: Storage, run_id: str, paragraph_ids: set[int]) -> dict[int, Paragraph]:
    return smap.paragraph_rows(session, run_id, paragraph_ids)


def _evidence_payloads(session: Storage, run_id: str, rows: list[Any]) -> list[dict[str, Any]]:
    """证据行按 ordinal 重组为原文引用，哈希由不可变原文切片重算"""
    return smap.evidence_payloads(session, run_id, rows)


def _global_positions(session: Storage, run_id: str, paragraph_ids: set[int]) -> dict[int, int]:
    """段落全文起点 = 所属正文起点 + 章内起点"""
    return smap.global_positions(session, run_id, paragraph_ids)


def _first_text_position(session: Storage, run_id: str, evidence: list[Any]) -> int:
    """完整事件/结果的正文排序位置由其自身证据派生"""
    positions = smap.global_positions(session, run_id, {int(ref.paragraph_id) for ref in evidence})
    return min(positions[int(ref.paragraph_id)] + int(ref.char_start) for ref in evidence)


def _run_events(session: Storage, run_id: str) -> dict[str, CompleteEvent]:
    return smap.run_events(session, run_id)


def _run_event_dicts(session: Storage, run_id: str) -> dict[str, dict[str, Any]]:
    """本 run 完整事件的读取形状：身份 + 当前内容 + 整体证据"""
    rows = _run_events(session, run_id)
    if not rows:
        return {}
    event_ids = list(rows)
    evidence = smap.fetch_evidence(session, "complete_event_id", event_ids)
    result: dict[str, dict[str, Any]] = {}
    for event_id, row in rows.items():
        payloads = _evidence_payloads(session, run_id, evidence.get(event_id, []))
        if not payloads:
            raise ValueError(f"正式事件缺少整体证据: event_id={event_id}")
        positions = _global_positions(session, run_id, {item["paragraph_id"] for item in payloads})
        result[event_id] = {
            "event_id": event_id,
            "title": row.title,
            "problem": row.problem,
            "summary": row.summary,
            "event_type": row.event_type,
            "status": row.status,
            "progress": row.progress,
            "first_text_position": min(positions[item["paragraph_id"]] + item["char_start"] for item in payloads),
            "evidence": payloads,
        }
    return result


def _run_annotation_records(session: Storage, run_id: str) -> list[Any]:
    """本 run 的章级标注记录：记录自身带 run/章归属，不经 work 推导"""
    return list(session.reads.event_trees_organization_run_annotation_records_1(run_id))


def _run_foreshadowing_actions(session: Storage, run_id: str) -> list[Any]:
    """本 run 的伏笔动作：来源或目标声明属于本 run 的声明集合"""
    declarations = run_declaration_ids(session, run_id)
    if not declarations:
        return []
    return list(session.reads.event_trees_organization_run_foreshadowing_actions_1(declarations))


def _page_size(limit: int, maximum: int = 100) -> None:
    if not 1 <= limit <= maximum:
        raise ValueError(f"limit 必须在 1 到 {maximum} 之间")


class EventOrganizationDraft:
    """只更新本轮内存；程序检查完整性后由诊断保存点一次提交"""

    def _identifier(self, *key):
        if key not in self._identifiers:
            self._identifiers[key] = new_id()
        return self._identifiers[key]

    def __init__(self, session: Storage, run_id: str, agent_id: str | None = None) -> None:
        # agent_id 是诊断整轮的会话身份（executions 的 session 形状），不是单个案例的调用
        self.session = session
        self.run_id = run_id
        self._identifiers: dict[tuple, str] = {}
        self.agent_id = agent_id
        self.producer_agent_id: str | None = None
        self.identity_snapshot: str | None = None
        self.structure_snapshot: str | None = None
        self.containments: dict[tuple[str, str], ContainmentDraft] = {}
        self.declaration_reviews: dict[str, DeclarationReviewDraft] = {}
        self.declaration_comparisons: dict[tuple[str, str], DeclarationComparisonDraft] = {}
        self.structure_reviews: dict[tuple[str, str], StructureReviewDraft] = {}
        self.events: dict[str, CompleteEventDraft] = {}
        self.relations: dict[str, RelationDraft] = {}
        self.arcs: dict[str, NarrativeArcDraft] = {}
        self.event_arc_links: dict[tuple[str, str], EventArcLinkDraft] = {}
        self.outcomes: dict[str, EventOutcomeDraft] = {}
        self.event_outcome_links: dict[tuple[str, str], EventOutcomeLinkDraft] = {}
        self.reviewed_events: dict[str, EventReviewDraft] = {}

    def _all_events(self) -> dict[str, dict[str, Any]]:
        result = _run_event_dicts(self.session, self.run_id)
        result.update({key: item.model_dump(mode="json") for key, item in self.events.items()})
        return result

    def _parents(self) -> dict[str, str]:
        parents = {
            row.contained_child_id: row.contained_parent_id
            for row in self.session.reads.event_trees_organization_parents_1(self.run_id)
            # ck_narrative_links_shape：包含形状两端同非空，读投影按该形状取非空对
            if row.contained_child_id is not None and row.contained_parent_id is not None
        }
        for edge in self.containments.values():
            prior = parents.get(edge.child_event_id)
            if prior is not None and prior != edge.parent_event_id:
                raise CandidateConflict(
                    f"包含候选存在多个直接父: child_event_id={edge.child_event_id}",
                    [
                        item.producer_agent_id
                        for item in self.containments.values()
                        if item.child_event_id == edge.child_event_id
                    ],
                )
            parents[edge.child_event_id] = edge.parent_event_id
        return parents

    @staticmethod
    def _event_hierarchy(event_id: str, parents: dict[str, str]) -> dict[str, Any]:
        """由实际包含关系给出合法结果端点，不把子事件贡献自动改挂到父事件"""
        root = event_id
        seen: set[str] = set()
        while root in parents:
            if root in seen:
                raise ValueError(f"完整事件包含关系形成环: {root}")
            seen.add(root)
            root = parents[root]
        return {
            "parent_event_id": parents.get(event_id),
            "top_level_event_id": root,
            "is_top_level": event_id == root,
        }

    def search_events(
        self,
        query: str = "",
        *,
        unreviewed_only: bool = False,
        top_level_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """分页返回本次草稿与正式事件，零事件时也可从过程读取开始"""
        _page_size(limit)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        parents = self._parents()
        rows = [
            {**item, **self._event_hierarchy(key, parents)}
            for key, item in self._all_events().items()
            if (not unreviewed_only or key not in self.reviewed_events)
            and (not top_level_only or key not in parents)
            and (
                not query
                or query.casefold()
                in " ".join(str(item[field]) for field in ("title", "problem", "summary")).casefold()
            )
        ]
        rows.sort(key=lambda item: (item["first_text_position"] or 0, item["event_id"]))
        return {
            "items": rows[offset : offset + limit],
            "total": len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
        }

    def read_events(self, event_ids: list[str]) -> list[dict[str, Any]]:
        _page_size(len(event_ids))
        by_id, parents = self._all_events(), self._parents()
        missing = sorted(set(event_ids) - set(by_id))
        if missing:
            declarations = smap.run_declaration_ids(self.session, self.run_id)
            sources = [key for key in missing if key in declarations]
            hint = (
                f"；其中 {sources} 是声明身份，事件关联须使用 search_events 返回的正式 event_id"
                if sources
                else ""
            )
            raise ValueError(f"本任务事件不存在: {missing}{hint}")
        return [
            {
                **by_id[key],
                **self._event_hierarchy(key, parents),
                "direct_child_event_ids": [child for child, parent in parents.items() if parent == key],
            }
            for key in event_ids
        ]

    def _declaration_rows(self) -> dict[str, dict[str, Any]]:
        """章级声明的正式读取：不可变声明 + 原标注记录/章节 + 参与者/证据/关系提议/伏笔动作"""
        session = self.session
        joined = _run_annotation_records(session, self.run_id)
        if not joined:
            return {}
        records = {entry.ChapterAnnotation.record_id: entry.ChapterAnnotation for entry in joined}
        chapter_by_record = {
            entry.ChapterAnnotation.record_id: (int(entry.ChapterAnnotation.chapter_id), int(entry.Chapter.sequence))
            for entry in joined
        }
        declarations = {
            row.declaration_id: row for row in session.reads.event_trees_organization_declaration_rows_3(records)
        }
        declaration_ids = list(declarations)
        if not declaration_ids:
            return {}
        participants: dict[str, list[dict[str, Any]]] = {key: [] for key in declaration_ids}
        names = {}
        participant_rows = list(session.reads.event_trees_organization_declaration_rows_1(declaration_ids))
        if participant_rows:
            names = {
                row.entity_id: row.canonical_name
                for row in session.reads.event_trees_organization_declaration_rows_4(participant_rows)
            }
        for row in participant_rows:
            participants[row.declaration_id].append(
                {
                    "entity": {
                        "name": names.get(row.entity_id, row.entity_id),
                        "entity_id": row.entity_id,
                    },
                    "role": row.role,
                    "narrative_role": row.narrative_role,
                    "action": row.action,
                    "emotion": row.emotion,
                }
            )
        evidence = smap.fetch_evidence(session, "declaration_id", declaration_ids)
        proposals: dict[str, list[dict[str, Any]]] = {key: [] for key in declaration_ids}
        link_rows = list(session.reads.event_trees_organization_declaration_rows_2(declaration_ids, self.run_id))
        link_evidence = smap.fetch_evidence(session, "narrative_link_id", [row.link_id for row in link_rows])
        action_rows = [
            row
            for row in _run_foreshadowing_actions(session, self.run_id)
            if row.source_declaration_id in declarations or row.target_declaration_id in declarations
        ]
        action_evidence = smap.fetch_evidence(
            session, "foreshadow_action_id", [row.action_id for row in action_rows]
        )
        grouped = smap.evidence_payload_groups(
            session,
            self.run_id,
            [evidence.get(identifier, []) for identifier in declaration_ids]
            + [link_evidence.get(row.link_id, []) for row in link_rows]
            + [action_evidence.get(row.action_id, []) for row in action_rows],
        )
        declaration_payloads = dict(zip(declaration_ids, grouped[: len(declaration_ids)], strict=True))
        link_payloads = dict(
            zip(
                [row.link_id for row in link_rows],
                grouped[len(declaration_ids) : len(declaration_ids) + len(link_rows)],
                strict=True,
            )
        )
        action_payloads = dict(
            zip(
                [row.action_id for row in action_rows],
                grouped[len(declaration_ids) + len(link_rows) :],
                strict=True,
            )
        )
        chapter_context = {
            producer: smap.annotation_chapter_of_execution(session, producer)
            for producer in {row.producer_agent_id for row in action_rows}
        }
        for link_row in link_rows:
            source_id, target_id = link_row.semantic_source_declaration_id, link_row.semantic_target_declaration_id
            payload: dict[str, Any] = {
                "relation_id": link_row.link_id,
                "source_declaration_id": source_id,
                "target_declaration_id": target_id,
                "relation_type": link_row.relation_type,
                "reason": link_row.reason,
                "evidence": link_payloads[link_row.link_id],
                "producer_agent_id": link_row.producer_agent_id,
            }
            for endpoint in (source_id, target_id):
                if endpoint in proposals:
                    proposals[endpoint].append(payload)
        actions: dict[str, list[dict[str, Any]]] = {key: [] for key in declaration_ids}
        for row in action_rows:
            source_context = chapter_context[row.producer_agent_id]
            chapter_id, chapter_order = source_context.chapter_id, source_context.chapter_order
            payload = {
                "action_id": row.action_id,
                "source_declaration_id": row.source_declaration_id,
                "target_declaration_id": row.target_declaration_id,
                "action_type": row.action_type,
                "chapter_id": chapter_id,
                "chapter_order": chapter_order,
                "evidence": action_payloads[row.action_id],
            }
            for endpoint in (row.source_declaration_id, row.target_declaration_id):
                if endpoint in actions:
                    actions[endpoint].append(payload)
        items: list[dict[str, Any]] = []
        for identifier, declaration in declarations.items():
            record = records[declaration.record_id]
            chapter_id, chapter_order = chapter_by_record[declaration.record_id]
            bound = declaration_payloads[identifier]
            if not bound:
                raise ValueError(f"声明缺少原文证据: {identifier}")
            payload = {
                "declaration_id": identifier,
                "title": declaration.title,
                "problem": declaration.problem,
                "summary": declaration.summary,
                "event_type": declaration.event_type,
                "status": declaration.status,
                "progress": declaration.progress,
                "participants": participants.get(identifier, []),
                "evidence": bound,
                "chapter_id": chapter_id,
                "chapter_order": chapter_order,
                "char_start": bound[0]["char_start"],
                "local_key": declaration.local_key,
                "producer_agent_id": record.agent_id,
            }
            payload.update(
                is_foreshadow_setup=declaration.is_foreshadowing_root,
                payoff_likelihood=declaration.payoff_likelihood,
                # strength 是 payoff_likelihood 的读投影，不双存第二份属性
                strength=declaration.payoff_likelihood,
                relation_proposals=proposals.get(identifier, []),
                source_actions=actions.get(identifier, []),
            )
            payload["source_hash"] = snapshot_digest(payload)
            items.append(payload)
        items.sort(key=lambda item: (item["chapter_order"], item["char_start"], item["declaration_id"]))
        return {item["declaration_id"]: item for item in items}

    def read_declarations(
        self, declaration_ids: list[str] | None = None, *, offset: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        """读取不可变声明；来源身份从不解释为正式事件身份"""
        _page_size(limit)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        all_rows = self._declaration_rows()
        if declaration_ids is not None:
            if not declaration_ids or len(set(declaration_ids)) != len(declaration_ids):
                raise ValueError("声明引用不能为空或重复")
            if set(declaration_ids) - set(all_rows):
                raise ValueError("声明引用不属于本 run")
            rows = [all_rows[key] for key in declaration_ids]
        else:
            rows = list(all_rows.values())
        return {
            "items": rows[offset : offset + limit],
            "total": len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
        }

    def _declarations(self) -> dict[str, dict[str, Any]]:
        return self._declaration_rows()

    def _source(self) -> dict[str, Any]:
        if not self.producer_agent_id:
            raise ValueError("诊断贡献缺少真实生产者")
        return {"producer_agent_id": self.producer_agent_id}

    def review_declarations(self, declaration_ids: list[str], *, reason: str) -> None:
        all_sources = self._declarations()
        if set(declaration_ids) - set(all_sources):
            raise ValueError("声明引用不属于本 run")
        rows = [all_sources[key] for key in declaration_ids]
        source = self._source()
        for row in rows:
            self.declaration_reviews[row["declaration_id"]] = DeclarationReviewDraft(
                declaration_id=row["declaration_id"], source_hash=row["source_hash"], reason=reason, **source
            )

    def _require_free_key(self, key: str, event_id: str) -> None:
        """局部键在同一执行内唯一：被其他事件占用时拒收，同一事件重发放行"""
        holder = next(
            (
                item
                for item in self.events.values()
                if item.producer_agent_id == self.producer_agent_id and item.local_key == key
            ),
            None,
        )
        if holder is not None and holder.event_id != event_id:
            raise ValueError(
                f"局部键已被本执行的其他事件占用: key={key} event_id={holder.event_id} title={holder.title}；"
                "同一执行内局部键必须唯一且不随章节、批次重置；请换用未占用的键（建议由声明 id 派生），"
                "或复用、撤回占用的候选后重新提交"
            )

    def identity(
        self,
        *,
        key: str,
        title: str,
        problem: str,
        summary: str,
        event_type: str,
        status: Literal["ongoing", "resolved"],
        declaration_ids: list[str],
        reason: str,
        evidence: list[OrganizationEvidence],
        progress: str | None = None,
    ) -> dict[str, Any]:
        """判断同一事件身份并保留全部章级声明，程序仅机械分配身份并保留所有来源原值"""
        if not declaration_ids or len(declaration_ids) != len(set(declaration_ids)):
            raise ValueError("声明列表不能为空或包含重复身份")
        all_sources = self._declarations()
        if set(declaration_ids) - set(all_sources):
            raise ValueError("声明引用不属于本 run")
        rows = [all_sources[key] for key in declaration_ids]
        event_id = self._identifier("event_identity", self.run_id, *sorted(declaration_ids))
        bound = self.bind_evidence(evidence)
        candidate = CompleteEventDraft(
            event_id=event_id,
            local_key=key,
            title=title,
            problem=problem,
            summary=summary,
            event_type=event_type,
            status=status,
            progress=progress,
            declaration_ids=sorted(declaration_ids),
            reason=reason,
            source_hashes={row["declaration_id"]: row["source_hash"] for row in rows},
            first_text_position=self._first_position(bound),
            evidence=bound,
            **self._source(),
        )
        existing = self.events.get(event_id)
        if existing is not None and existing.producer_agent_id != self.producer_agent_id:
            raise ValueError("身份候选已由其他生产者提交，不能覆盖其判断")
        # 同一声明只能被一个事件认领，
        # 重叠认领的第二份在提交时拒收，由模型在原会话内改判（撤回或复用既有事件）
        for identifier in declaration_ids:
            holder = next((item for item in self.events.values() if identifier in item.declaration_ids), None)
            if holder is None or holder.event_id == event_id:
                continue
            if holder.producer_agent_id == self.producer_agent_id:
                raise ValueError(
                    f"声明已被当前生产者既有事件认领: declaration_id={identifier} event_id={holder.event_id}；"
                    "复用该事件或先撤回原候选再提交"
                )
            raise ValueError(
                f"声明已被其他生产者提交的事件认领: declaration_id={identifier} event_id={holder.event_id}；"
                "不得重复认领，复用该事件并在来源比较中处置"
            )
        self._require_free_key(key, event_id)
        self.events = {**self.events, event_id: candidate}
        self.reviewed_events.pop(event_id, None)
        return {"status": "accepted_candidate", "event_id": event_id, "declaration_ids": declaration_ids}

    def compare_declarations(
        self,
        *,
        source_declaration_id: str,
        target_declaration_ids: list[str],
        disposition: Literal["same_event", "independent", "related"],
        reason: str,
        evidence: list[OrganizationEvidence],
    ) -> None:
        """显式处置远近来源比较，责任锚点不决定故事语义"""
        rows = self._declarations()
        source = rows.get(source_declaration_id)
        if (
            source is None
            or not target_declaration_ids
            or len(set(target_declaration_ids)) != len(target_declaration_ids)
        ):
            raise ValueError("比较端点不存在或重复")
        source_order = (source["chapter_order"], source["char_start"], source_declaration_id)
        for target_id in target_declaration_ids:
            target = rows.get(target_id)
            if target is None or (target["chapter_order"], target["char_start"], target_id) <= source_order:
                raise ValueError("比较来源必须是配对中更早的真实来源；请以更早一端为 source 提交")
            existing = self.declaration_comparisons.get((source_declaration_id, target_id))
            if existing is not None and existing.producer_agent_id != self.producer_agent_id:
                raise ValueError("来源比较已由其他生产者提交，不能覆盖")
        item = DeclarationComparisonDraft(
            source_declaration_id=source_declaration_id,
            target_declaration_ids=target_declaration_ids,
            disposition=disposition,
            reason=reason,
            evidence=self.bind_evidence(evidence),
            **self._source(),
        )
        for target_id in target_declaration_ids:
            self.declaration_comparisons[(source_declaration_id, target_id)] = item

    def _references_to(self, event_id: str) -> list[tuple[str, str]]:
        """引用指定事件的行：(结构名称, 生产者)，含证据内的事件引用"""
        found: list[tuple[str, str]] = []
        referencing: tuple[tuple[str, dict[Any, Any], tuple[str, ...]], ...] = (
            ("事件核对", self.reviewed_events, ("event_id",)),
            ("结构对", self.structure_reviews, ("source_event_id", "target_event_id")),
            ("包含", self.containments, ("parent_event_id", "child_event_id")),
            ("事件关系", self.relations, ("source_id", "target_id")),
            ("叙事线关联", self.event_arc_links, ("event_id",)),
            ("结果关联", self.event_outcome_links, ("event_id",)),
        )
        for name, container, fields in referencing:
            for item in container.values():
                if any(getattr(item, field) == event_id for field in fields):
                    found.append((name, item.producer_agent_id))
        evidence_rows: tuple[tuple[str, dict[Any, Any]], ...] = (
            ("事件证据", self.events),
            ("包含证据", self.containments),
            ("关系证据", self.relations),
            ("来源比较证据", self.declaration_comparisons),
            ("结构对证据", self.structure_reviews),
            ("叙事线证据", self.arcs),
            ("结果证据", self.outcomes),
            ("叙事线关联证据", self.event_arc_links),
            ("结果关联证据", self.event_outcome_links),
        )
        for name, container in evidence_rows:
            for item in container.values():
                if any(ref.event_id == event_id for ref in item.evidence):
                    found.append((name, item.producer_agent_id))
        return found

    def _drop_own_references(self, event_id: str) -> None:
        """撤回前清除本生产者引用该事件的行；其余记录证据只清事件引用字段，证据本身保留"""
        referencing: tuple[tuple[dict[Any, Any], tuple[str, ...]], ...] = (
            (self.reviewed_events, ("event_id",)),
            (self.structure_reviews, ("source_event_id", "target_event_id")),
            (self.containments, ("parent_event_id", "child_event_id")),
            (self.relations, ("source_id", "target_id")),
            (self.event_arc_links, ("event_id",)),
            (self.event_outcome_links, ("event_id",)),
        )
        for container, fields in referencing:
            for key, item in list(container.items()):
                if item.producer_agent_id == self.producer_agent_id and any(
                    getattr(item, field) == event_id for field in fields
                ):
                    del container[key]
        carriers: tuple[dict[Any, Any], ...] = (
            self.events,
            self.containments,
            self.relations,
            self.declaration_comparisons,
            self.structure_reviews,
            self.arcs,
            self.outcomes,
            self.event_arc_links,
            self.event_outcome_links,
        )
        for container in carriers:
            for key, item in list(container.items()):
                if item.producer_agent_id != self.producer_agent_id:
                    continue
                if any(ref.event_id == event_id for ref in item.evidence):
                    container[key] = item.model_copy(
                        update={
                            "evidence": [
                                ref.model_copy(update={"event_id": None}) if ref.event_id == event_id else ref
                                for ref in item.evidence
                            ]
                        }
                    )

    def retract(
        self,
        *,
        kind: Literal["identity", "contain", "relation"],
        identifier: str,
        reason: str,
        evidence: list[OrganizationEvidence],
    ) -> None:
        """只允许实际生产者在对应屏障前撤回自己的候选，原操作仍保留审计"""
        if not reason.strip():
            raise ValueError("撤回须明确理由")
        self.bind_evidence(evidence)
        records: Any = {"identity": self.events, "contain": self.containments, "relation": self.relations}[kind]
        key: Any = tuple(identifier.split("/", 1)) if kind == "contain" else identifier
        item = records.get(key)
        if item is None or item.producer_agent_id != self.producer_agent_id:
            raise ValueError("只能撤回当前生产者的实际候选")
        if kind == "identity":
            foreign = sorted(
                {name for name, producer in self._references_to(identifier) if producer != self.producer_agent_id}
            )
            if foreign:
                raise ValueError(
                    f"事件已被其他执行引用（{'、'.join(foreign)}），不能撤回；"
                    "请改用其他事件，或由引用方处置后再撤回"
                )
            self._drop_own_references(identifier)
        del records[key]

    def event(
        self,
        *,
        key: str,
        title: str,
        problem: str,
        summary: str,
        event_type: str,
        status: Literal["ongoing", "resolved"],
        reason: str,
        compared_event_ids: list[str],
        evidence: list[OrganizationEvidence],
        progress: str | None = None,
    ) -> dict[str, Any]:
        """跨章新增事件必须明确核对整个已有身份目录，不从名称猜测身份"""
        if set(compared_event_ids) != set(self.events) or len(compared_event_ids) != len(set(compared_event_ids)):
            raise ValueError("新增事件须明确核对当前全部候选事件身份；同一事件应复用已有 event_id")
        source = self._source()
        bound = self.bind_evidence(evidence)
        event_id = self._identifier("cross_chapter_event", self.run_id, self.producer_agent_id, key)
        candidate = CompleteEventDraft(
            event_id=event_id,
            local_key=key,
            title=title,
            problem=problem,
            summary=summary,
            event_type=event_type,
            status=status,
            progress=progress,
            reason=reason,
            first_text_position=self._first_position(bound),
            evidence=bound,
            **source,
        )
        self._require_free_key(key, event_id)
        if event_id in self.events and self.events[event_id] != candidate:
            raise ValueError("已接受事件不能被其他操作覆盖")
        self.events[event_id] = candidate
        return {"status": "accepted_candidate", "event_id": event_id}

    def contain(
        self, *, parent_event_id: str, child_event_id: str, reason: str, evidence: list[OrganizationEvidence]
    ) -> None:
        self.read_events([parent_event_id, child_event_id])
        if parent_event_id == child_event_id:
            raise ValueError("事件不能包含自身")
        # 一个子事件只能有一个直接父、包含不成环，
        # 冲突的第二份包含在提交时拒收，由模型在原会话内改判
        parents = self._parents()
        holder = parents.get(child_event_id)
        if holder is not None and holder != parent_event_id:
            raise ValueError(
                f"子事件已有直接父: child_event_id={child_event_id} parent_event_id={holder}；"
                "一个子事件只能有一个直接父，改挂须先撤回原包含候选"
            )
        cursor: str | None = parent_event_id
        seen: set[str] = set()
        while cursor is not None:
            if cursor == child_event_id:
                raise ValueError(f"包含与既有包含关系成环: parent={parent_event_id} child={child_event_id}")
            if cursor in seen:
                break
            seen.add(cursor)
            cursor = parents.get(cursor)
        edge = ContainmentDraft(
            parent_event_id=parent_event_id,
            child_event_id=child_event_id,
            reason=reason,
            evidence=self.bind_evidence(evidence),
            **self._source(),
        )
        previous = self.containments.get((parent_event_id, child_event_id))
        if previous is not None and previous.producer_agent_id != self.producer_agent_id:
            raise ValueError("不能覆盖其他生产者提交的包含候选，请引用原判断或显式交接")
        self.containments = {**self.containments, (parent_event_id, child_event_id): edge}
        # 保留旧核对及其真实作者；屏障发现来源改变后回原案例，不丢失修正责任

    def structure_review(
        self,
        *,
        source_event_id: str,
        target_event_id: str,
        disposition: Literal["contains", "part_of", "related", "independent"],
        reason: str,
        evidence: list[OrganizationEvidence],
    ) -> None:
        self.read_events([source_event_id, target_event_id])
        if source_event_id == target_event_id:
            raise ValueError("同一正式事件不能与自身作结构比较")
        bound = self.bind_evidence(evidence)
        pair = min(source_event_id, target_event_id), max(source_event_id, target_event_id)
        self.structure_reviews[pair] = StructureReviewDraft(
            source_event_id=source_event_id,
            target_event_id=target_event_id,
            disposition=disposition,
            reason=reason,
            evidence=bound,
            snapshot_hash=self.pair_snapshot(*pair),
            **self._source(),
        )

    def pair_snapshot(self, source: str, target: str) -> str:
        return snapshot_digest(
            {
                "events": [self.events[key].model_dump(mode="json") for key in sorted((source, target))],
                "containments": record_payloads(
                    item
                    for item in self.containments.values()
                    if {item.parent_event_id, item.child_event_id} == {source, target}
                ),
                "relations": record_payloads(
                    item for item in self.relations.values() if {item.source_id, item.target_id} == {source, target}
                ),
            }
        )

    def validate_events(self, events: dict[str, CompleteEventDraft] | None = None) -> None:
        """逐事件核对来源哈希与身份归属；声明覆盖与事实核对缺口不再作为保存条件"""
        events = self.events if events is None else events
        declarations = self._declarations()
        used: dict[str, str] = {}
        for event in events.values():
            for identifier in event.declaration_ids:
                if identifier in used and used[identifier] != event.event_id:
                    raise CandidateConflict(
                        f"声明身份候选相冲突: declaration_id={identifier}",
                        [item.producer_agent_id for item in events.values() if identifier in item.declaration_ids],
                    )
                source = declarations.get(identifier)
                if source is None or event.source_hashes.get(identifier) != source["source_hash"]:
                    raise ValueError(f"声明来源不存在或已改变: {identifier}")
                used[identifier] = event.event_id
        for identifier, review in self.declaration_reviews.items():
            source = declarations.get(identifier)
            if source is None or review.source_hash != source["source_hash"]:
                raise ValueError(f"声明事实核对的来源已改变: {identifier}")

    def relate_events(
        self,
        *,
        key: str,
        source_kind: Literal["event"],
        source_id: str,
        target_kind: Literal["event"],
        target_id: str,
        relation_type: str,
        reason: str,
        evidence: list[OrganizationEvidence],
    ) -> str:
        self.read_events([source_id, target_id])
        if relation_type in {"main", "secondary", "contains", "containment", "same_identity"}:
            raise ValueError("身份、包含及旧主链标记不能伪装为普通事件关系")
        relation_id = self._identifier("event_relation", self.run_id, self.producer_agent_id, key)
        self.relations[relation_id] = RelationDraft(
            relation_id=relation_id,
            source_kind=source_kind,
            source_id=source_id,
            target_kind=target_kind,
            target_id=target_id,
            relation_type=relation_type,
            reason=reason,
            evidence=self.bind_evidence(evidence),
            source_operation_id=key,
            **self._source(),
        )
        # 核对快照故意保留，新增关系不能把原核对作者与剩余额度一起抹掉
        return relation_id

    def read_passages(self, paragraph_ids: list[int], offset: int = 0, limit: int = 10) -> dict[str, Any]:
        """有界读取真实原文；段号从工具回执获得，长段落按字符续读"""
        _page_size(len(paragraph_ids), 20)
        _page_size(limit, 20)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        rows = self.session.reads.event_trees_organization_read_passages_1(paragraph_ids, self.run_id)
        if set(paragraph_ids) - {row.paragraph_id for row in rows}:
            raise ValueError("本任务原文段落不存在")
        return {
            "items": [
                {
                    "paragraph_id": row.paragraph_id,
                    "chapter_id": row.chapter_id,
                    "text": row.text[offset : offset + 2000],
                    "next_offset": offset + 2000 if len(row.text) > offset + 2000 else None,
                }
                for row in rows[:limit]
            ]
        }

    def bind_evidence(self, evidence: list[OrganizationEvidence]) -> list[BoundOrganizationEvidence]:
        """沿用原文锚点的逐字绑定规则，不接受模型提交坐标或哈希"""
        _page_size(len(evidence))
        event_ids = list({item.event_id for item in evidence if item.event_id is not None})
        if event_ids:
            self.read_events(event_ids)
        paragraph_ids = {item.paragraph_id for item in evidence}
        paragraphs = _paragraph_rows(self.session, self.run_id, paragraph_ids)
        bound = []
        for item in evidence:
            row = paragraphs.get(item.paragraph_id)
            if row is None:
                raise ValueError(f"本任务原文段落不存在: {item.paragraph_id}")
            start, end = 0, len(row.text)
            if item.quote is not None:
                start = -1
                for _ in range(item.occurrence):
                    start = row.text.find(item.quote, start + 1)
                    if start < 0:
                        raise ValueError("quote 或 occurrence 不匹配原文")
                end = start + len(item.quote)
            elif item.occurrence != 1:
                raise ValueError("完整段落引用 occurrence 必须为 1")
            bound.append(
                BoundOrganizationEvidence(
                    event_id=item.event_id,
                    paragraph_id=row.paragraph_id,
                    chapter_id=row.chapter_id,
                    char_start=start,
                    char_end=end,
                    text_hash=text_digest(row.text[start:end]),
                )
            )
        return bound

    def _first_position(self, evidence: list[BoundOrganizationEvidence]) -> int:
        positions = _global_positions(self.session, self.run_id, {ref.paragraph_id for ref in evidence})
        return min(positions[ref.paragraph_id] + ref.char_start for ref in evidence)

    def register_arc(
        self,
        *,
        key: str,
        kind: Literal["main", "subplot"],
        title: str,
        objective: str,
        role: str,
        reason: str,
        evidence: list[OrganizationEvidence],
        parent_arc_id: str | None = None,
    ) -> str:
        """登记或修正叙事线，不据数量和局部树键推定主线"""
        if not key.strip():
            raise ValueError("叙事线稳定键不能为空")
        arc_id = self._identifier("narrative_arc", self.run_id, self.producer_agent_id, key)
        arc = NarrativeArcDraft(
            arc_id=arc_id,
            kind=kind,
            title=title,
            objective=objective,
            role=role,
            reason=reason,
            parent_arc_id=parent_arc_id,
            evidence=self.bind_evidence(evidence),
            **self._source(),
        )
        candidates = {**self.arcs, arc_id: arc}
        NarrativeOrganization(arcs=list(candidates.values()))
        self.arcs = candidates
        return arc_id

    def review_events(self, event_ids: list[str], *, reason: str) -> None:
        """核对正式产物；无可证关联时明确说明，禁止为了覆盖而编造关联"""
        self.read_events(event_ids)
        reviews = {
            event_id: EventReviewDraft(
                event_id=event_id, reason=reason, snapshot_hash=self.event_snapshot(event_id), **self._source()
            )
            for event_id in event_ids
        }
        self.reviewed_events.update(reviews)

    def link_event_arc(
        self, *, event_id: str, arc_id: str, role: str, reason: str, evidence: list[OrganizationEvidence]
    ) -> None:
        """同一完整事件可关联多线，各项关系独立保存理由与证据"""
        self.read_events([event_id])
        if arc_id not in self.arcs:
            raise ValueError("叙事线关联端点不存在")
        link = EventArcLinkDraft(
            event_id=event_id,
            arc_id=arc_id,
            role=role,
            reason=reason,
            evidence=self.bind_evidence(evidence),
            **self._source(),
        )
        self.event_arc_links[(event_id, arc_id)] = link

    def register_outcome(self, *, key: str, title: str, description: str, evidence: list[OrganizationEvidence]) -> str:
        """结果身份由本轮稳定键派生，不包含任何来源事件身份"""
        if not key.strip():
            raise ValueError("结果稳定键不能为空")
        outcome_id = self._identifier("event_outcome", self.run_id, self.producer_agent_id, key)
        bound = self.bind_evidence(evidence)
        self.outcomes[outcome_id] = EventOutcomeDraft(
            outcome_id=outcome_id,
            title=title,
            description=description,
            evidence=bound,
            first_text_position=self._first_position(bound),
            **self._source(),
        )
        return outcome_id

    def link_event_outcome(
        self, *, event_id: str, outcome_id: str, reason: str, evidence: list[OrganizationEvidence]
    ) -> None:
        """结果贡献只接受顶层完整事件，关系证据不能省略或借用结果证据"""
        self.read_events([event_id])
        if outcome_id not in self.outcomes:
            raise ValueError("结果关联端点不存在")
        hierarchy = self._event_hierarchy(event_id, self._parents())
        if not hierarchy["is_top_level"]:
            raise ValueError(
                "全书结果贡献端点必须是顶层完整事件，子事件进展保存在章节产物中；"
                f"event_id={event_id}，parent_event_id={hierarchy['parent_event_id']}，"
                f"top_level_event_id={hierarchy['top_level_event_id']}。"
                "请核对顶层事件后重新提交该贡献的理由和证据，本次未自动替换端点"
            )
        link = EventOutcomeLinkDraft(
            event_id=event_id,
            outcome_id=outcome_id,
            reason=reason,
            evidence=self.bind_evidence(evidence),
            **self._source(),
        )
        self.event_outcome_links[(event_id, outcome_id)] = link

    def _validate_subject(self, kind: str, subject_id: str) -> None:
        if kind == "event":
            self.read_events([subject_id])
        elif kind == "declaration":
            self.read_declarations([subject_id])
        elif kind == "fact":
            try:
                fact_id = str(subject_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("冲突事实主体必须是正式图谱事实流水号") from exc
            row = self.session.reads.event_trees_organization_validate_subject_1(fact_id)
            producer_agent_id = None if row is None else row.direct_producer_agent_id
            if producer_agent_id is None or not _execution_in_run(self.session, producer_agent_id, self.run_id):
                raise ValueError("冲突事实主体不存在或不属于本 run")
        else:
            raise ValueError("冲突主体类型无效")

    def read_draft(self, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """分别分页检查组织事实和完整事件覆盖审计"""
        _page_size(limit)
        if offset < 0:
            raise ValueError("offset 不能为负数")
        groups: dict[str, list[BaseModel]] = {
            "events": list(self.events.values()),
            "relations": list(self.relations.values()),
            "arcs": list(self.arcs.values()),
            "event_arc_links": list(self.event_arc_links.values()),
            "outcomes": list(self.outcomes.values()),
            "event_outcome_links": list(self.event_outcome_links.values()),
            "reviewed_events": list(self.reviewed_events.values()),
        }
        return {
            **{
                name: [item.model_dump(mode="json") for item in values[offset : offset + limit]]
                for name, values in groups.items()
            },
            "totals": {name: len(values) for name, values in groups.items()},
        }

    def event_snapshot(self, event_id: str) -> str:
        return snapshot_digest(
            {
                "event": self.events[event_id].model_dump(mode="json"),
                "containments": record_payloads(
                    item
                    for item in self.containments.values()
                    if event_id in {item.parent_event_id, item.child_event_id}
                ),
                "relations": record_payloads(
                    item for item in self.relations.values() if event_id in {item.source_id, item.target_id}
                ),
            }
        )

    def identity_digest(self) -> str:
        """身份摘要：按当前已提交候选实时计算，用于报告绑定与保存快照"""
        return snapshot_digest(
            [
                item.model_dump(mode="json")
                for item in sorted(
                    (item for item in self.events.values() if item.declaration_ids), key=lambda item: item.event_id
                )
            ]
        )

    def structure_digest(self) -> str:
        """结构摘要：按当前事件、包含与关系实时计算，用于报告绑定与保存快照"""
        return snapshot_digest(
            {
                "events": record_payloads(self.events.values()),
                "containments": record_payloads(self.containments.values()),
                "relations": record_payloads(self.relations.values()),
            }
        )

    def finish(self) -> NarrativeOrganization:
        self.validate_events()
        self.identity_snapshot = self.identity_digest()
        self.structure_snapshot = self.structure_digest()
        result = NarrativeOrganization(
            source_agent_id=self.agent_id,
            events=list(self.events.values()),
            relations=list(self.relations.values()),
            arcs=list(self.arcs.values()),
            event_arc_links=list(self.event_arc_links.values()),
            outcomes=list(self.outcomes.values()),
            event_outcome_links=list(self.event_outcome_links.values()),
            reviewed_events=list(self.reviewed_events.values()),
            declaration_reviews=list(self.declaration_reviews.values()),
            declaration_comparisons=list(
                {
                    snapshot_digest(item.model_dump(mode="json")): item
                    for item in self.declaration_comparisons.values()
                }.values()
            ),
            containments=list(self.containments.values()),
            identity_snapshot=self.identity_snapshot,
            structure_snapshot=self.structure_snapshot,
            structure_reviews=list(self.structure_reviews.values()),
        )
        validate_organization(self.session, self.run_id, result)
        return result


def _execution_in_run(session: Storage, agent_id: str, run_id: str) -> bool:
    """真实执行的本 run 归属：调用形状直接带 run，整轮会话形状带 session_run"""
    return smap.execution_in_run(session, agent_id, run_id)


def _annotation_chapter_of_execution(session: Storage, agent_id: str) -> tuple[int | None, int | None]:
    """章级伏笔动作的来源章序：从其真实生产执行的记录归属与章节取得"""
    return smap.annotation_chapter_of_execution(session, agent_id)


def validate_organization(session: Storage, run_id: str, organization: NarrativeOrganization) -> None:
    """保存前核对同 run 端点、独立结果及每项真实证据；核对覆盖缺口不作为保存条件"""
    organization = NarrativeOrganization.model_validate(organization.model_dump())
    records = _run_annotation_records(session, run_id)
    all_ids = set(_run_events(session, run_id))
    all_ids.update(item.event_id for item in organization.events)
    draft = EventOrganizationDraft(session, run_id)
    draft.events = {item.event_id: item for item in organization.events}
    draft.declaration_reviews = {item.declaration_id: item for item in organization.declaration_reviews}
    draft.containments = {(item.parent_event_id, item.child_event_id): item for item in organization.containments}
    draft.relations = {item.relation_id: item for item in organization.relations}
    draft.reviewed_events = {item.event_id: item for item in organization.reviewed_events}
    draft.structure_reviews = {
        (min(item.source_event_id, item.target_event_id), max(item.source_event_id, item.target_event_id)): item
        for item in organization.structure_reviews
    }
    for item in organization.declaration_comparisons:
        for target in item.target_declaration_ids:
            draft.declaration_comparisons[(item.source_declaration_id, target)] = item
    draft.validate_events()
    if draft.identity_digest() != organization.identity_snapshot:
        raise ValueError("身份快照与实际来源判断不一致")
    if draft.structure_digest() != organization.structure_snapshot:
        raise ValueError("结构快照与实际接受记录不一致")
    child_ids = set(draft._parents())
    for linked_event_id in [item.event_id for item in organization.event_arc_links] + [
        item.event_id for item in organization.event_outcome_links
    ]:
        if linked_event_id not in all_ids:
            raise ValueError("关联完整事件端点不属于本 run")
    if child_ids & {link.event_id for link in organization.event_outcome_links}:
        raise ValueError("全书结果贡献端点必须是顶层完整事件")
    refs = [
        ref
        for records in (
            organization.events,
            organization.relations,
            organization.arcs,
            organization.outcomes,
            organization.event_arc_links,
            organization.event_outcome_links,
            organization.containments,
            organization.declaration_comparisons,
            organization.structure_reviews,
        )
        for item in records
        for ref in item.evidence
    ]
    for records in (
        organization.events,
        organization.containments,
        organization.relations,
        organization.arcs,
        organization.event_arc_links,
        organization.outcomes,
        organization.event_outcome_links,
        organization.declaration_comparisons,
    ):
        for record in records:
            if not record.producer_agent_id:
                raise ValueError("诊断贡献缺少真实 Agent 写出者")
    paragraphs = _paragraph_rows(session, run_id, {ref.paragraph_id for ref in refs})
    for ref in refs:
        row = paragraphs.get(ref.paragraph_id)
        if (
            row is None
            or int(row.chapter_id) != ref.chapter_id
            or ref.char_end > len(row.text)
            or text_digest(row.text[ref.char_start : ref.char_end]) != ref.text_hash
        ):
            raise ValueError("组织证据坐标或哈希与本 run 原文不一致")
        if ref.event_id is not None and ref.event_id not in all_ids:
            raise ValueError("组织证据引用的完整事件不属于本 run")
    positioned_records: list[CompleteEventDraft | EventOutcomeDraft] = [*organization.events, *organization.outcomes]
    positions = _global_positions(session, run_id, {ref.paragraph_id for ref in refs})
    for outcome in positioned_records:
        if outcome.first_text_position != min(positions[ref.paragraph_id] + ref.char_start for ref in outcome.evidence):
            raise ValueError("结果正文排序位置必须由证据派生")
