from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.knowledge.authority import GraphAuthorityView, ParticipantState, RelationEvent
from src.storage.models import Chunk as ChunkModel
from src.storage.models import Novel


def insert_graph_test_novel(db_session, novel_id: str) -> None:
    """
    创建时间: 2026-04-23
    任务: 复杂度与耦合审查 P2 - 测试工程化
    说明: 为 graph snapshot contract 测试补 novels 主表记录。
    """
    if len(novel_id) > 8:
        raise ValueError(f"graph snapshot test novel_id must be 8 chars or fewer, got: {novel_id}")

    db_session.add(
        Novel(
            novel_id=novel_id,
            filename=f"{novel_id}.txt",
            file_path=f"data/uploads/{novel_id}.txt",
            file_size=128,
        )
    )
    db_session.commit()


def insert_graph_test_chunks(db_session, run_id: str, chunk_ids: range) -> None:
    """
    创建时间: 2026-04-23
    任务: 复杂度与耦合审查 P2 - 测试工程化
    说明: 为 graph relation event 测试补齐 chunks 外键依赖。
    """
    db_session.add_all(
        [
            ChunkModel(
                chunk_id=chunk_id,
                run_id=run_id,
                text=f"chunk-{chunk_id}",
            )
            for chunk_id in chunk_ids
        ]
    )
    db_session.commit()


def create_graph_annotation_repo(session=object()) -> MagicMock:
    """
    创建时间: 2026-04-23
    任务: 复杂度与耦合审查 P2 - 测试工程化
    说明: 统一构造 graph fetcher 所需 annotation repo 假对象，避免每个测试重复 mock 同一协议。
    """
    annotation_repo = MagicMock()
    annotation_repo.session = session
    annotation_repo.fetch_pending_chunk_relations.return_value = []
    return annotation_repo


def relation_event(
    relation_event_id: int,
    *,
    chunk_id: int,
    from_entity_id: int = 1,
    to_entity_id: int = 2,
    from_name: str = "沈砚",
    to_name: str = "陆明",
    relation_type: str = "盟友",
    change_type: str = "新建",
    confidence: float = 0.8,
) -> RelationEvent:
    """
    创建时间: 2026-04-23
    任务: 复杂度与耦合审查 P2 - 测试工程化
    说明: 以语义字段构造 RelationEvent，测试里只覆盖关注字段。
    """
    return RelationEvent(
        relation_event_id=relation_event_id,
        chunk_id=chunk_id,
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        from_name=from_name,
        to_name=to_name,
        relation_type=relation_type,
        change_type=change_type,
        confidence=confidence,
    )


def participant_state(
    entity_id: int,
    *,
    name: str,
    entity_type: str = "character",
    status: str = "active",
    primary_role_function: str | None = None,
    first_seen_chunk: int | None = None,
    last_seen_chunk: int | None = None,
    source_confidence: float | None = None,
) -> ParticipantState:
    """
    创建时间: 2026-04-26
    任务: graph participant contract tests
    说明: 统一构造 ParticipantState，避免测试继续散落旧 StableState 语义。
    """
    return ParticipantState(
        entity_id=entity_id,
        name=name,
        entity_type=entity_type,
        status=status,
        primary_role_function=primary_role_function,
        first_seen_chunk=first_seen_chunk,
        last_seen_chunk=last_seen_chunk,
        source_confidence=source_confidence,
    )


def build_graph_authority_view(
    *,
    participant_states: Sequence[ParticipantState] | None = None,
    confirmed_relations: Sequence[object] | None = None,
    relation_events: Sequence[RelationEvent] | None = None,
    canonical_entities: Sequence[object] | None = None,
) -> GraphAuthorityView:
    """
    创建时间: 2026-04-26
    任务: graph participant contract tests
    说明: 统一按 participant_states 构造 GraphAuthorityView，降低测试重构噪音。
    """
    return GraphAuthorityView(
        canonical_entities=list(canonical_entities or []),
        participant_states=list(participant_states or []),
        confirmed_relations=list(confirmed_relations or []),
        relation_events=list(relation_events or []),
    )


def get_graph_participant_states(view: GraphAuthorityView | SimpleNamespace) -> list[object]:
    """
    创建时间: 2026-04-26
    任务: graph participant contract tests
    说明: 统一读取 graph participant slice，避免测试里散落直接属性访问。
    """
    return list(getattr(view, "participant_states", []))


class StaticGraphAuthorityService:
    """
    创建时间: 2026-04-23
    任务: 复杂度与耦合审查 P2 - 测试工程化
    说明: 固定返回 GraphAuthorityView 或 allowlist namespace，用于页面合约组装测试。
    """

    def __init__(
        self,
        *,
        expected_run_id: str,
        view: GraphAuthorityView | SimpleNamespace,
        forbid_report: bool = False,
    ) -> None:
        self.expected_run_id = expected_run_id
        self.view = view
        self.forbid_report = forbid_report

    def build_graph_view(self, run_id: str) -> GraphAuthorityView | SimpleNamespace:
        assert run_id == self.expected_run_id
        return self.view

    def build_graph_report(self, *_args, **_kwargs):
        if self.forbid_report:
            raise AssertionError("/graph page should not consume diagnosis/export graph report")
        return None


class PaginatedGraphAuthorityService:
    """
    创建时间: 2026-04-23
    任务: 复杂度与耦合审查 P2 - 测试工程化
    说明: 提供增量事件分页接口，锁定 graph events 不重建完整 report 的行为。
    """

    def __init__(
        self,
        *,
        expected_run_id: str,
        relation_events: Sequence[RelationEvent],
        view: GraphAuthorityView | None = None,
        forbid_view: bool = False,
        forbid_report: bool = False,
    ) -> None:
        self.expected_run_id = expected_run_id
        self._relation_events = list(relation_events)
        self.view = view
        self.forbid_view = forbid_view
        self.forbid_report = forbid_report

    def build_graph_view(self, run_id: str) -> GraphAuthorityView:
        if self.forbid_view:
            raise AssertionError("graph events pagination should not rebuild the full graph view")
        assert run_id == self.expected_run_id
        return self.view or build_graph_authority_view(
            participant_states=[],
            confirmed_relations=[],
            relation_events=self._relation_events,
        )

    def build_graph_report(self, *_args, **_kwargs):
        if self.forbid_report:
            raise AssertionError("graph events pagination should not depend on graph report")
        return None

    def build_graph_relation_event_page(
        self,
        run_id: str,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[RelationEvent], int]:
        assert run_id == self.expected_run_id
        end = offset + (limit or len(self._relation_events))
        return self._relation_events[offset:end], len(self._relation_events)


def patch_graph_authority_service(monkeypatch, service) -> None:
    """
    创建时间: 2026-04-23
    任务: 复杂度与耦合审查 P2 - 测试工程化
    说明: 统一替换 KnowledgeGraphAuthorityService.from_session，测试只关心传入 service 的语义。
    """
    monkeypatch.setattr(
        "src.api.routes.results_fetchers.fetchers.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: service,
    )
