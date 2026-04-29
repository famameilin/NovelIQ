from __future__ import annotations

import uuid

from src.chunking.chunker import Chunk
from src.storage.models import ChunkRelation, GraphEntityParticipant
from src.storage.repositories import ChunkRepository, GraphRepository, RunRepository
from src.workflows.annotate_helpers.graph_projection import project_graph_tables


def _insert_test_novel(db_session, novel_id: str) -> None:
    """
    创建时间: 2026-04-26
    任务: graph participant projection tests
    说明: 为 graph projection 测试补 novels 主表记录，避免 run 外键失败。
    """
    from src.storage.models import Novel

    db_session.add(
        Novel(
            novel_id=novel_id,
            filename=f"{novel_id}.txt",
            file_path=f"data/uploads/{novel_id}.txt",
            file_size=128,
        )
    )
    db_session.commit()


def test_project_graph_tables_builds_and_rebuilds_graph_entity_participants(db_session) -> None:
    novel_id = uuid.uuid4().hex[:8]
    _insert_test_novel(db_session, novel_id)
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph Participant Projection",
    )
    chunk_repo = ChunkRepository(db_session)
    chunk_repo.insert_chunks(run_id, [Chunk(index=1, text="测试1", start=0, end=100)])

    db_session.add(
        ChunkRelation(
            chunk_id=1,
            run_id=run_id,
            from_char="林渡",
            to_char="顾霜",
            type="盟友",
            change="新建",
            evidence="并肩迎敌",
            confidence=0.92,
            projection_status="pending",
        )
    )
    db_session.commit()

    project_graph_tables(run_id=run_id, to_chunk=1, session=db_session)

    graph_repo = GraphRepository(db_session)
    participants = {item.name: item for item in graph_repo.fetch_participant_entities(run_id)}
    assert set(participants.keys()) == {"林渡", "顾霜"}
    assert participants["林渡"].relation_event_count == 1
    assert participants["林渡"].current_degree == 1

    extra = graph_repo.upsert_entity(run_id=run_id, canonical_name="路人甲", first_seen_chunk=1, last_seen_chunk=1)
    db_session.add(
        GraphEntityParticipant(
            run_id=run_id,
            entity_id=extra.entity_id,
            relation_event_count=99,
            current_degree=0,
            historical_degree=0,
        )
    )
    db_session.commit()
    assert graph_repo.count_entity_participants(run_id) == 3

    project_graph_tables(run_id=run_id, to_chunk=1, session=db_session, rebuild=True)

    rebuilt_participants = {item.name: item for item in graph_repo.fetch_participant_entities(run_id)}
    assert set(rebuilt_participants.keys()) == {"林渡", "顾霜"}
    assert graph_repo.count_entity_participants(run_id) == 2


def test_project_graph_tables_removes_stale_relation_when_change_becomes_no_change(db_session) -> None:
    """
    创建时间: 2026-04-27
    创建者: Codex
    任务: fix-graph-projection-no-change-refresh
    说明: 已投影的关系若后来被修正为“无变化”，graph event/current relation/participant projection
          都必须一起回刷，不能继续残留旧图谱状态。
    """
    novel_id = uuid.uuid4().hex[:8]
    _insert_test_novel(db_session, novel_id)
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph No Change Cleanup",
    )
    chunk_repo = ChunkRepository(db_session)
    chunk_repo.insert_chunks(run_id, [Chunk(index=1, text="测试1", start=0, end=100)])

    relation = ChunkRelation(
        chunk_id=1,
        run_id=run_id,
        from_char="林渡",
        to_char="顾霜",
        type="盟友",
        change="新建",
        evidence="并肩迎敌",
        confidence=0.92,
        source_model="phase4",
        projection_status="pending",
    )
    db_session.add(relation)
    db_session.commit()

    project_graph_tables(run_id=run_id, to_chunk=1, session=db_session)

    graph_repo = GraphRepository(db_session)
    assert graph_repo.count_relation_events(run_id) == 1
    assert graph_repo.count_current_relations(run_id) == 1
    assert graph_repo.count_entity_participants(run_id) == 2

    relation.change = "无变化"
    relation.projection_status = "pending"
    relation.projected_at = None
    db_session.commit()

    project_graph_tables(run_id=run_id, from_chunk=1, to_chunk=1, session=db_session)

    assert graph_repo.count_relation_events(run_id) == 0
    assert graph_repo.count_current_relations(run_id, active_only=None) == 0
    assert graph_repo.count_entity_participants(run_id) == 0


def test_project_graph_tables_keeps_unresolved_pronoun_endpoint_pending(db_session) -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    说明: 未解析代词端点不能被 graph projection upsert 成实体，关系行必须显式 pending 并记录错误原因。
    """
    novel_id = uuid.uuid4().hex[:8]
    _insert_test_novel(db_session, novel_id)
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph Pronoun Endpoint",
    )
    chunk_repo = ChunkRepository(db_session)
    chunk_repo.insert_chunks(run_id, [Chunk(index=1, text="我看见沈砚。", start=0, end=100)])

    relation = ChunkRelation(
        chunk_id=1,
        run_id=run_id,
        from_char="我",
        to_char="沈砚",
        type="盟友",
        change="新建",
        evidence="我看见沈砚",
        confidence=0.8,
        projection_status="pending",
    )
    db_session.add(relation)
    db_session.commit()

    project_graph_tables(run_id=run_id, to_chunk=1, session=db_session)

    db_session.refresh(relation)
    graph_repo = GraphRepository(db_session)
    entity_names = {entity.canonical_name for entity in graph_repo.fetch_entities(run_id)}

    assert relation.projection_status == "pending"
    assert relation.projection_error == "unresolved global-character endpoint"
    assert "我" not in entity_names
    assert graph_repo.count_relation_events(run_id) == 0


def test_project_graph_tables_uses_resolved_pronoun_endpoint_without_aliasing_surface(db_session) -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 已解析“我 -> 汪淼”可以投影为汪淼关系，但不能把“我”写成 graph alias。
    """
    novel_id = uuid.uuid4().hex[:8]
    _insert_test_novel(db_session, novel_id)
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Graph Resolved Pronoun Endpoint",
    )
    chunk_repo = ChunkRepository(db_session)
    chunk_repo.insert_chunks(run_id, [Chunk(index=1, text="我看见沈砚。", start=0, end=100)])

    relation = ChunkRelation(
        chunk_id=1,
        run_id=run_id,
        from_char="我",
        to_char="沈砚",
        from_reference_kind="pov_slot",
        to_reference_kind="global_character",
        resolved_from_global_name="汪淼",
        resolved_to_global_name="沈砚",
        type="盟友",
        change="新建",
        evidence="我看见沈砚",
        confidence=0.8,
        projection_status="pending",
    )
    db_session.add(relation)
    db_session.commit()

    project_graph_tables(run_id=run_id, to_chunk=1, session=db_session)

    db_session.refresh(relation)
    graph_repo = GraphRepository(db_session)
    entity_names = {entity.canonical_name for entity in graph_repo.fetch_entities(run_id)}
    alias_map = graph_repo.fetch_alias_map(run_id)

    assert relation.projection_status == "projected"
    assert entity_names == {"汪淼", "沈砚"}
    assert alias_map.get("我") is None
    assert graph_repo.count_relation_events(run_id) == 1
