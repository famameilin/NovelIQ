"""诊断真实执行上下文对接标注共享读取，不建立虚假的章级 work"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from src.agents.annotation.shared_tools import ObjectKind
from src.agents.annotation.text_search import TextSearchService
from src.event_trees.organization import EventOrganizationDraft
from src.fact_graph.outputs import SourceReference
from src.fact_graph.read.storage_projection import graph_projection
from src.storage import Storage


@dataclass
class DiagnosisTextAccess:
    """本诊断调用授予的原文引用，单独的诊断阶段而非伪造章节身份"""

    run_scope: str
    phase: str = "diagnosis_open"
    allow_future_context: bool = True
    current_chapter_id: None = None
    paragraph_info: None = None
    authorized_text_paragraph_ids: set[int] = field(default_factory=set)
    text_references: dict[str, SourceReference] = field(default_factory=dict)
    search_log: list[dict[str, Any]] = field(default_factory=list)

    def append_search_log(self, item: dict[str, Any]) -> None:
        self.search_log.append(item)


class DiagnosisTextQuery:
    """复用标注原文搜索服务，并把读取限定在当前 run"""

    def __init__(self, session: Storage, run_id: str, search: TextSearchService | None) -> None:
        self.session, self.run_id, self.search = (session, run_id, search)

    async def search_text(self, query: str, *, range_name: str, limit: int = 50) -> Any:
        if self.search is not None:
            return await self.search.search(query, limit=limit)
        from src.config import settings
        from src.embedding import EmbeddingClient

        config = settings.models.paragraph_embedding
        client = EmbeddingClient() if config.semantic_enabled else None
        try:
            service = TextSearchService(
                self.session,
                run_id=self.run_id,
                embedding_client=client,
                semantic_enabled=config.semantic_enabled,
                semantic_top_k=config.top_k,
            )
            return await service.search(query, limit=limit)
        finally:
            if client is not None:
                await client.aclose()

    async def read_paragraph(self, paragraph_id: int, *, allow_future_context: bool) -> dict[str, Any]:
        row = self.session.reads.work_queries_paragraph_record(self.run_id, paragraph_id)
        if row is None:
            raise ValueError(f"paragraph_id={paragraph_id} 不属于本 run")
        return {"chapter_id": row.chapter_id, "paragraph_id": row.paragraph_id, "text": row.text}


class DiagnosisAnnotationEventSource:
    """共享入口读取不可变章级来源，不暴露过程及 owner 身份"""

    def __init__(self, draft: EventOrganizationDraft) -> None:
        self.draft = draft

    def search_ids(
        self, query: str, *, chapter_id: int | None, tree_id: str | None, isforeshadowing: bool | None = None
    ) -> list[str]:
        if tree_id is not None:
            raise ValueError("事件没有正式事件树身份，请按 chapter_id 或正文词检索")
        return [
            key
            for key, item in self.draft._all_events().items()
            if (chapter_id is None or item.get("from", item.get("from_chapter_id")) == chapter_id)
            and (isforeshadowing is None or bool(item.get("is_foreshadowing_root")) == isforeshadowing)
            and (query.casefold() in " ".join(str(item[field]) for field in ("title", "problem", "summary")).casefold())
        ]

    def read(self, event_id: str) -> dict[str, Any]:
        item = self.draft.read_events([event_id])[0]
        return self._record(event_id, item)

    def search_page(
        self, query: str, *, chapter_id: int | None, tree_id: str | None,
        isforeshadowing: bool | None, offset: int, limit: int,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        "一次装载事件与结构，索引和本页详情使用同一快照"
        if tree_id is not None:
            raise ValueError("事件没有正式事件树身份，请按 chapter_id 或正文词检索")
        by_id, parents = self.draft.read_view()
        identifiers = [
            key for key, item in by_id.items()
            if (chapter_id is None or item.get("from", item.get("from_chapter_id")) == chapter_id)
            and (isforeshadowing is None or bool(item.get("is_foreshadowing_root")) == isforeshadowing)
            and query.casefold() in " ".join(str(item[field]) for field in ("title", "problem", "summary")).casefold()
        ]
        children: dict[str, list[str]] = {}
        for child, parent in parents.items():
            children.setdefault(parent, []).append(child)
        return identifiers, [
            self._record(key, {**by_id[key], **self.draft._event_hierarchy(key, parents),
                               "direct_child_event_ids": children.get(key, [])})
            for key in identifiers[offset:offset + limit]
        ]

    @staticmethod
    def _record(event_id: str, item: dict[str, Any]) -> dict[str, Any]:
        return {
            **item,
            "event_id": event_id,
            "node_id": event_id,
            "chapter_id": item.get("from", item.get("from_chapter_id")),
            **{
                key: item[key]
                for key in (
                    "parent_event_id",
                    "top_level_event_id",
                    "is_top_level",
                    "ancestor_event_ids",
                    "direct_child_event_ids",
                )
                if key in item
            },
            "saved": True,
            "content": {
                **item,
                "is_foreshadow_setup": bool(item.get("is_foreshadowing_root")),
                "description": item["summary"],
                "evidence_paragraph_id": item["evidence"][0]["paragraph_id"],
            },
        }


class DiagnosisOrganizationSource:
    """完整事件与诊断草稿显式分类，读取不产生核对或写入副作用"""

    def __init__(self, draft: EventOrganizationDraft) -> None:
        self.draft = draft

    def _rows(self, kind: ObjectKind) -> list[dict[str, Any]]:
        if kind == "event":
            by_id, parents = self.draft.read_view()
            return [{**item, **self.draft._event_hierarchy(key, parents)} for key, item in by_id.items()]
        if kind == "arc":
            return [item.model_dump(mode="json") for item in self.draft.arcs.values()]
        if kind == "outcome":
            return [item.model_dump(mode="json") for item in self.draft.outcomes.values()]
        raise ValueError(f"无诊断对象 kind={kind}")

    def search(
        self, kind: ObjectKind, query: str, *, chapter_id: int | None, tree_id: str | None
    ) -> list[dict[str, Any]]:
        if tree_id is not None:
            raise ValueError("事件和正式事件不接受旧 tree_id；请明确 kind")
        rows = self._rows(kind)
        return [
            {
                "kind": kind,
                **{
                    key: value[:160]
                    if isinstance(value, str) and key in {"title", "problem", "summary", "reason"}
                    else value
                    for key, value in item.items()
                    if key
                    in {
                        "event_id",
                        "arc_id",
                        "outcome_id",
                        "title",
                        "problem",
                        "summary",
                        "subject_kind",
                        "subject_id",
                        "reason",
                        "status",
                        "parent_event_id",
                        "top_level_event_id",
                        "is_top_level",
                    }
                },
            }
            for item in rows
            if query.casefold() in str(item).casefold()
            and (chapter_id is None or any(value.get("chapter_id") == chapter_id for value in item.get("evidence", [])))
        ]

    def read(self, kind: ObjectKind, identifier: str) -> dict[str, Any]:
        id_field = {"event": "event_id", "arc": "arc_id", "outcome": "outcome_id"}[kind]
        item = next((row for row in self._rows(kind) if row[id_field] == identifier), None)
        if item is None:
            raise ValueError(f"kind={kind} 的本任务对象不存在: {identifier}")
        if kind == "event":
            item = {
                **item,
                "arc_links": [
                    link.model_dump(mode="json")
                    for link in self.draft.event_arc_links.values()
                    if link.event_id == identifier
                ],
                "outcome_links": [
                    link.model_dump(mode="json")
                    for link in self.draft.event_outcome_links.values()
                    if link.event_id == identifier
                ],
                "relations": [
                    link.model_dump(mode="json")
                    for link in self.draft.relations.values()
                    if identifier in {link.source_id, link.target_id}
                ],
            }
        return {"kind": kind, **item}


class DiagnosisGraphSource:
    """正式身份视图的只读适配，延迟读取以保留取证故障的真实调用审计"""

    def __init__(self, session: Storage, run_id: str) -> None:
        self.session, self.run_id = (session, run_id)
        self._view: Any = None
        self._lock = threading.RLock()

    def refresh(self) -> None:
        "使下一次读取重新装载正式图谱"
        with self._lock:
            self._view = None

    def _load(self) -> Any:
        with self._lock:
            if self._view is None:
                from src.fact_graph.read import KnowledgeGraphAuthorityService

                self._view = KnowledgeGraphAuthorityService.from_session(self.session).build_level1_snapshot(
                    self.run_id,
                )
            return self._view

    @property
    def entity_names(self) -> dict[str, str]:
        return {item.entity_id: item.name for item in self._load().canonical_entities if item.entity_id}

    @property
    def entity_types(self) -> dict[str, str]:
        return {item.entity_id: item.entity_type for item in self._load().canonical_entities if item.entity_id}

    @property
    def entity_attributes(self) -> dict[str, Any]:
        from src.fact_graph.read.entities import fetch_latest_entities

        pass
        rows = fetch_latest_entities(graph_projection(self.session.graph), self.run_id)
        by_id = {str(item.entity_id): item.state for item in rows}
        return {
            item.entity_id: {**by_id.get(item.entity_id, {}), "aliases": item.aliases}
            for item in self._load().canonical_entities
            if item.entity_id
        }

    @property
    def active_relations(self) -> set[tuple[str, str, str]]:
        return {
            (item.from_entity_id, item.to_entity_id, item.relation_type)
            for item in self._load().confirmed_relations
            if item.from_entity_id and item.to_entity_id
        }

    def entity_id_for_key(self, key: str) -> str:
        return key

    def resolve_entity_id(self, identifier: str, *, label: str) -> str:
        if identifier not in self.entity_names:
            raise ValueError(f"{label}={identifier} 不属于本 run 的正式身份")
        return identifier

    def display_name(self, key: str) -> str:
        return self.entity_names[key]


def graph_signals(session: Storage, run_id: str) -> dict[str, Any]:
    """原图谱统计随指标读取提供，实际故障向外传播，不伪装空数据"""
    from src.fact_graph.read import KnowledgeGraphAuthorityService, serialize_graph_report_signals

    report = KnowledgeGraphAuthorityService.from_session(session).build_graph_report(run_id)
    summary, quality = serialize_graph_report_signals(report)
    return {**summary, **quality}
