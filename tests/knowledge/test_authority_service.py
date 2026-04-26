from __future__ import annotations

import uuid

import pytest

from src.knowledge.authority import (
    EXPORT_GRAPH_AUTHORITY_DEPENDENCY_FIELDS,
    GRAPH_PAGE_AUTHORITY_DEPENDENCY_FIELDS,
    GRAPH_REPORT_AUTHORITY_DEPENDENCY_FIELDS,
    LEVEL1_AUTHORITY_DEPENDENCY_FIELDS,
    TIMELINE_AUTHORITY_DEPENDENCY_FIELDS,
    GraphAuthorityReport,
    GraphPageQualityDetails,
    GraphPageSummary,
    KnowledgeGraphAuthorityService,
)
from src.storage.models import Chunk as ChunkModel
from src.storage.models import Novel
from src.storage.repositories import GraphRepository, RunRepository


def _create_run_with_novel(db_session, *, title: str) -> tuple[str, str]:
    """创建 authority 测试所需的小说和 run 记录。"""
    novel_id = uuid.uuid4().hex[:8]
    db_session.add(
        Novel(
            novel_id=novel_id,
            title=title,
            filename=f"{novel_id}.txt",
            file_path=f"data/uploads/{novel_id}.txt",
            file_size=100,
        )
    )
    db_session.commit()
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title=title,
    )
    db_session.add_all(
        [
            ChunkModel(
                chunk_id=chunk_id,
                chapter_id=None,
                text=f"chunk-{chunk_id}",
                run_id=run_id,
            )
            for chunk_id in range(1, 256)
        ]
    )
    db_session.commit()
    return novel_id, run_id


def test_build_timeline_view_only_exposes_character_subgraph_and_break_events(db_session) -> None:
    novel_id, run_id = _create_run_with_novel(db_session, title="Timeline Authority View")

    graph_repo = GraphRepository(db_session)
    protagonist = graph_repo.upsert_entity(
        run_id=run_id,
        canonical_name="叶青",
        entity_type="character",
        first_seen_chunk=1,
        last_seen_chunk=8,
    )
    rival = graph_repo.upsert_entity(
        run_id=run_id,
        canonical_name="沈昭",
        entity_type="character",
        first_seen_chunk=2,
        last_seen_chunk=9,
    )
    sect = graph_repo.upsert_entity(
        run_id=run_id,
        canonical_name="玄霄宗",
        entity_type="organization",
        first_seen_chunk=1,
        last_seen_chunk=9,
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=protagonist.entity_id,
        to_entity_id=rival.entity_id,
        relation_type="盟友",
        change_type="断裂",
        chunk_id=9,
        evidence="二人决裂",
        confidence=0.81,
        source_relation_row_id=12001,
        directionality="directed",
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=protagonist.entity_id,
        to_entity_id=sect.entity_id,
        relation_type="归属",
        change_type="新建",
        chunk_id=3,
        evidence="加入宗门",
        confidence=0.95,
        source_relation_row_id=12002,
        directionality="directed",
    )
    db_session.commit()

    view = KnowledgeGraphAuthorityService.from_session(db_session).build_timeline_view(run_id)
    character_ids = {entity.entity_id for entity in view.character_entities}

    assert {entity.name for entity in view.character_entities} == {"叶青", "沈昭"}
    assert all(entity.entity_type == "character" for entity in view.character_entities)
    assert {(event.from_name, event.to_name, event.change_type) for event in view.relation_events} == {
        ("叶青", "沈昭", "断裂")
    }
    assert {
        (event.chunk_id, event.relation_type, event.change_type, event.evidence) for event in view.relation_events
    } == {(9, "盟友", "断裂", "二人决裂")}
    assert all(
        event.from_entity_id in character_ids and event.to_entity_id in character_ids for event in view.relation_events
    )
    assert {(item.name, item.first_seen_chunk, item.last_seen_chunk) for item in view.entity_lifecycles} == {
        ("叶青", 1, 8),
        ("沈昭", 2, 9),
    }
    assert all(item.entity_type == "character" for item in view.entity_lifecycles)
    assert all(item.entity_id in character_ids for item in view.entity_lifecycles)


def test_build_graph_view_exposes_participant_states_without_transient_local_context(db_session) -> None:
    novel_id, run_id = _create_run_with_novel(db_session, title="Graph Authority View")

    graph_repo = GraphRepository(db_session)
    hero = graph_repo.upsert_entity(
        run_id=run_id,
        canonical_name="周渡",
        entity_type="character",
        first_seen_chunk=1,
        last_seen_chunk=6,
        primary_role_function="protagonist",
        last_emotion_score="angry",
        last_action="拔刀",
        source_confidence=0.88,
    )
    ally = graph_repo.upsert_entity(
        run_id=run_id,
        canonical_name="顾霜",
        entity_type="character",
        first_seen_chunk=2,
        last_seen_chunk=6,
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=ally.entity_id,
        relation_type="盟友",
        change_type="新建",
        chunk_id=4,
        evidence="联手破阵",
        confidence=0.93,
        source_relation_row_id=13001,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, hero.entity_id, ally.entity_id)
    graph_repo.refresh_entity_participants(run_id, [hero.entity_id, ally.entity_id])
    db_session.commit()

    view = KnowledgeGraphAuthorityService.from_session(db_session).build_graph_view(run_id)

    assert {(state.name, state.primary_role_function, state.status) for state in view.participant_states} == {
        ("周渡", "protagonist", "active"),
        ("顾霜", None, "active"),
    }
    assert all(not hasattr(state, "last_action") for state in view.participant_states)
    assert all(not hasattr(state, "last_emotion_score") for state in view.participant_states)
    assert not hasattr(view, "summary")
    assert not hasattr(view, "quality")


def test_build_graph_report_keeps_export_and_diagnosis_on_summary_quality_only(db_session) -> None:
    novel_id, run_id = _create_run_with_novel(db_session, title="Graph Authority Report")

    graph_repo = GraphRepository(db_session)
    hero = graph_repo.upsert_entity(run_id=run_id, canonical_name="苏镜", first_seen_chunk=1, last_seen_chunk=5)
    ally = graph_repo.upsert_entity(run_id=run_id, canonical_name="程霜", first_seen_chunk=2, last_seen_chunk=5)
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=ally.entity_id,
        relation_type="盟友",
        change_type="新建",
        chunk_id=3,
        evidence="联手破局",
        confidence=0.52,
        source_relation_row_id=13021,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, hero.entity_id, ally.entity_id)
    graph_repo.refresh_entity_participants(run_id, [hero.entity_id, ally.entity_id])
    db_session.commit()

    report = KnowledgeGraphAuthorityService.from_session(db_session).build_graph_report(run_id)

    assert report.summary.node_count == 2
    assert report.summary.edge_count == 1
    assert report.quality.low_confidence_count == 1
    assert report.quality.conflict_count == 0
    assert not hasattr(report.summary, "core_characters")
    assert not hasattr(report.summary, "key_relations")
    assert not hasattr(report.quality, "conflicts")
    assert not hasattr(report.quality, "low_confidence_samples")
    assert not hasattr(report, "participant_states")
    assert not hasattr(report, "confirmed_relations")
    assert not hasattr(report, "relation_events")


def test_build_graph_view_requires_participant_projection_when_relation_tables_exist(db_session) -> None:
    novel_id, run_id = _create_run_with_novel(db_session, title="Graph Participant Consistency")

    graph_repo = GraphRepository(db_session)
    hero = graph_repo.upsert_entity(run_id=run_id, canonical_name="苏镜", first_seen_chunk=1, last_seen_chunk=5)
    ally = graph_repo.upsert_entity(run_id=run_id, canonical_name="程霜", first_seen_chunk=2, last_seen_chunk=5)
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=ally.entity_id,
        relation_type="盟友",
        change_type="新建",
        chunk_id=3,
        evidence="联手破局",
        confidence=0.52,
        source_relation_row_id=13041,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, hero.entity_id, ally.entity_id)
    db_session.commit()

    with pytest.raises(RuntimeError, match="graph participant projection is stale or incomplete"):
        KnowledgeGraphAuthorityService.from_session(db_session).build_graph_view(run_id)


def test_build_graph_view_rejects_partial_participant_projection_when_relations_exist(db_session) -> None:
    novel_id, run_id = _create_run_with_novel(db_session, title="Graph Participant Partial Consistency")

    graph_repo = GraphRepository(db_session)
    hero = graph_repo.upsert_entity(run_id=run_id, canonical_name="苏镜", first_seen_chunk=1, last_seen_chunk=5)
    ally = graph_repo.upsert_entity(run_id=run_id, canonical_name="程霜", first_seen_chunk=2, last_seen_chunk=5)
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=ally.entity_id,
        relation_type="盟友",
        change_type="新建",
        chunk_id=3,
        evidence="联手破局",
        confidence=0.52,
        source_relation_row_id=13042,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, hero.entity_id, ally.entity_id)
    graph_repo.refresh_entity_participants(run_id, [hero.entity_id])
    db_session.commit()

    with pytest.raises(RuntimeError, match="graph participant projection is stale or incomplete"):
        KnowledgeGraphAuthorityService.from_session(db_session).build_graph_view(run_id)


def test_graph_authority_report_rejects_graph_page_contracts() -> None:
    # 中文注释：report 是 diagnosis/export 的共享边界，必须拒绝 graph page
    # contract，避免页面字段被错误地重新序列化进共享 payload。
    with pytest.raises(TypeError, match="GraphAuthorityReport.summary must be GraphSharedSummary"):
        GraphAuthorityReport(
            summary=GraphPageSummary(node_count=2, edge_count=1, density=0.5, core_characters=["苏镜"]),
        )

    with pytest.raises(TypeError, match="GraphAuthorityReport.quality must be GraphQualitySignals"):
        GraphAuthorityReport(
            quality=GraphPageQualityDetails(
                conflict_count=1,
                low_confidence_count=2,
            )
        )


def test_build_export_view_keeps_export_graph_payloads_off_repository_shapes(db_session) -> None:
    novel_id, run_id = _create_run_with_novel(db_session, title="Export Graph Authority View")

    graph_repo = GraphRepository(db_session)
    hero = graph_repo.upsert_entity(run_id=run_id, canonical_name="苏镜", first_seen_chunk=1, last_seen_chunk=5)
    ally = graph_repo.upsert_entity(run_id=run_id, canonical_name="程霜", first_seen_chunk=2, last_seen_chunk=5)
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=ally.entity_id,
        relation_type="spouse_of",
        change_type="新建",
        chunk_id=5,
        evidence="并肩回府",
        confidence=0.78,
        source_relation_row_id=13031,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, hero.entity_id, ally.entity_id)
    graph_repo.refresh_entity_participants(run_id, [hero.entity_id, ally.entity_id])
    db_session.commit()

    export_view = KnowledgeGraphAuthorityService.from_session(db_session).build_export_view(run_id)

    assert {entity.name for entity in export_view.canonical_entities} == {"苏镜", "程霜"}
    assert len(export_view.current_relations) == 1
    assert export_view.current_relations[0].relation_id is not None
    assert export_view.current_relations[0].from_name == "苏镜"
    assert export_view.current_relations[0].relation_type == "spouse_of"
    assert export_view.current_relations[0].last_seen_chunk == 5
    assert len(export_view.relation_events) == 1
    assert export_view.relation_events[0].chunk_id == 5
    assert not hasattr(export_view, "summary")
    assert not hasattr(export_view, "quality")


def test_build_active_entity_view_normalizes_repository_rows_into_authority_contract(db_session) -> None:
    novel_id, run_id = _create_run_with_novel(db_session, title="Active Entity Authority View")

    graph_repo = GraphRepository(db_session)
    graph_repo.upsert_entity(
        run_id=run_id,
        canonical_name="白芷",
        entity_type="organization",
        last_seen_chunk=12,
        primary_role_function="helper",
        last_action="观察",
        last_emotion_score="平静",
        status="active",
    )
    db_session.commit()

    view = KnowledgeGraphAuthorityService.from_session(db_session).build_active_entity_view(
        run_id,
        current_chunk=12,
        lookback=5,
    )

    assert len(view) == 1
    assert view[0].name == "白芷"
    assert view[0].role == "helper"
    assert view[0].entity_type == "organization"
    assert view[0].status == "active"
    assert view[0].recent_action == "观察"
    assert view[0].recent_emotion == "平静"
    assert view[0].last_seen_chunk == 12
    assert not hasattr(view[0], "last_action")
    assert not hasattr(view[0], "last_emotion")


def test_build_level1_snapshot_entities_exclude_transient_prompt_local_state(db_session) -> None:
    novel_id, run_id = _create_run_with_novel(db_session, title="Level1 Stable Entity Contract")

    graph_repo = GraphRepository(db_session)
    graph_repo.upsert_entity(
        run_id=run_id,
        canonical_name="陆九",
        first_seen_chunk=1,
        last_seen_chunk=4,
        last_emotion_score="angry",
        last_action="拔刀",
    )
    db_session.commit()

    snapshot = KnowledgeGraphAuthorityService.from_session(db_session).build_level1_snapshot(run_id)

    assert len(snapshot.canonical_entities) == 1
    assert not hasattr(snapshot.canonical_entities[0], "last_action")
    assert not hasattr(snapshot.canonical_entities[0], "last_emotion_score")
    assert not hasattr(snapshot, "relation_events")
    assert not hasattr(snapshot, "participant_states")
    assert not hasattr(snapshot, "summary")
    assert not hasattr(snapshot, "quality")


def test_build_level1_snapshot_keeps_inactive_relations_outside_confirmed_relations(db_session) -> None:
    novel_id, run_id = _create_run_with_novel(db_session, title="Level1 Snapshot")

    graph_repo = GraphRepository(db_session)
    han_li = graph_repo.upsert_entity(run_id=run_id, canonical_name="韩立", first_seen_chunk=1, last_seen_chunk=7)
    nan_gong = graph_repo.upsert_entity(run_id=run_id, canonical_name="南宫婉", first_seen_chunk=1, last_seen_chunk=7)
    graph_repo.upsert_alias(
        run_id=run_id,
        entity_id=han_li.entity_id,
        alias="韩道友",
        source_chunk_id=1,
        evidence="称呼",
        confidence=0.9,
        source_type="named",
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=han_li.entity_id,
        to_entity_id=nan_gong.entity_id,
        relation_type="爱慕",
        change_type="新建",
        chunk_id=3,
        evidence="暗生情愫",
        confidence=0.8,
        source_relation_row_id=14001,
        directionality="directed",
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=han_li.entity_id,
        to_entity_id=nan_gong.entity_id,
        relation_type="爱慕",
        change_type="断裂",
        chunk_id=7,
        evidence="关系断裂",
        confidence=0.75,
        source_relation_row_id=14002,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, han_li.entity_id, nan_gong.entity_id)
    graph_repo.refresh_entity_participants(run_id, [han_li.entity_id, nan_gong.entity_id])
    db_session.commit()

    service = KnowledgeGraphAuthorityService.from_session(db_session)
    snapshot = service.build_level1_snapshot(run_id)
    graph_view = service.build_graph_view(run_id)

    assert ("韩立", "韩立") in {(item.alias, item.canonical) for item in snapshot.alias_mappings}
    assert snapshot.confirmed_relations == []
    assert {(event.from_name, event.to_name, event.change_type) for event in graph_view.relation_events} == {
        ("韩立", "南宫婉", "断裂"),
        ("韩立", "南宫婉", "新建"),
    }


def test_build_graph_view_summary_stays_consistent_with_inactive_edges(db_session) -> None:
    novel_id, run_id = _create_run_with_novel(db_session, title="Graph View Summary Contract")

    graph_repo = GraphRepository(db_session)
    hero = graph_repo.upsert_entity(run_id=run_id, canonical_name="林渡", first_seen_chunk=1, last_seen_chunk=8)
    ally = graph_repo.upsert_entity(run_id=run_id, canonical_name="顾霜", first_seen_chunk=1, last_seen_chunk=8)
    rival = graph_repo.upsert_entity(run_id=run_id, canonical_name="谢危", first_seen_chunk=2, last_seen_chunk=8)

    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=ally.entity_id,
        relation_type="盟友",
        change_type="新建",
        chunk_id=3,
        evidence="并肩迎敌",
        confidence=0.92,
        source_relation_row_id=15001,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, hero.entity_id, ally.entity_id)
    graph_repo.refresh_entity_participants(run_id, [hero.entity_id, ally.entity_id])

    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=rival.entity_id,
        relation_type="敌对",
        change_type="新建",
        chunk_id=4,
        evidence="结下仇怨",
        confidence=0.58,
        source_relation_row_id=15002,
        directionality="directed",
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=rival.entity_id,
        relation_type="敌对",
        change_type="断裂",
        chunk_id=8,
        evidence="恩怨了结",
        confidence=0.55,
        source_relation_row_id=15003,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, hero.entity_id, rival.entity_id)
    graph_repo.refresh_entity_participants(run_id, [hero.entity_id, rival.entity_id])
    db_session.commit()

    service = KnowledgeGraphAuthorityService.from_session(db_session)
    view = service.build_graph_view(run_id)
    report = service.build_graph_report(run_id)

    # Current graph view should expose only active relations; broken history stays in relation_events.
    assert len(view.confirmed_relations) == 1
    assert {(item.from_name, item.to_name, item.relation_type) for item in view.confirmed_relations} == {
        ("林渡", "顾霜", "盟友")
    }
    assert report.summary.edge_count == 1
    assert report.summary.density == 0.1667
    assert report.quality.low_confidence_count == 2


def test_build_graph_view_relation_events_are_full_history_not_page_window(db_session) -> None:
    novel_id, run_id = _create_run_with_novel(db_session, title="Graph View Full History")

    graph_repo = GraphRepository(db_session)
    hero = graph_repo.upsert_entity(run_id=run_id, canonical_name="林渡", first_seen_chunk=1, last_seen_chunk=205)
    ally = graph_repo.upsert_entity(run_id=run_id, canonical_name="顾霜", first_seen_chunk=1, last_seen_chunk=205)

    for chunk_id in range(1, 206):
        graph_repo.insert_relation_event(
            run_id=run_id,
            from_entity_id=hero.entity_id,
            to_entity_id=ally.entity_id,
            relation_type="盟友",
            change_type="波动" if chunk_id > 1 else "新建",
            chunk_id=chunk_id,
            evidence=f"事件 {chunk_id}",
            confidence=0.7,
            source_relation_row_id=17000 + chunk_id,
            directionality="directed",
        )

    graph_repo.refresh_current_relation(run_id, hero.entity_id, ally.entity_id)
    graph_repo.refresh_entity_participants(run_id, [hero.entity_id, ally.entity_id])
    db_session.commit()

    view = KnowledgeGraphAuthorityService.from_session(db_session).build_graph_view(run_id)

    assert len(view.relation_events) == 205
    assert view.relation_events[0].chunk_id == 205
    assert view.relation_events[-1].chunk_id == 1


def test_build_graph_report_caps_low_confidence_count_to_legacy_summary_limit(db_session) -> None:
    novel_id, run_id = _create_run_with_novel(db_session, title="Graph Report Low Confidence Cap")

    graph_repo = GraphRepository(db_session)
    hero = graph_repo.upsert_entity(run_id=run_id, canonical_name="林渡", first_seen_chunk=1, last_seen_chunk=25)
    ally = graph_repo.upsert_entity(run_id=run_id, canonical_name="顾霜", first_seen_chunk=1, last_seen_chunk=25)

    for chunk_id in range(1, 26):
        graph_repo.insert_relation_event(
            run_id=run_id,
            from_entity_id=hero.entity_id,
            to_entity_id=ally.entity_id,
            relation_type="盟友",
            change_type="波动" if chunk_id > 1 else "新建",
            chunk_id=chunk_id,
            evidence=f"低置信事件 {chunk_id}",
            confidence=0.55,
            source_relation_row_id=17500 + chunk_id,
            directionality="directed",
        )

    graph_repo.refresh_current_relation(run_id, hero.entity_id, ally.entity_id)
    graph_repo.refresh_entity_participants(run_id, [hero.entity_id, ally.entity_id])
    db_session.commit()

    report = KnowledgeGraphAuthorityService.from_session(db_session).build_graph_report(run_id)

    # 中文注释：report 是 export/diagnosis 共用的聚合口径，仍需保持旧 summary
    # 的上限行为；graph page 的全历史计数由独立 contract 负责覆盖。
    assert report.quality.low_confidence_count == 20
    assert report.quality.conflict_count == 0


def test_graph_report_counts_match_graph_page_shared_stats(db_session) -> None:
    novel_id, run_id = _create_run_with_novel(db_session, title="Graph Report Shared Stats")

    graph_repo = GraphRepository(db_session)
    hero = graph_repo.upsert_entity(run_id=run_id, canonical_name="林渡", first_seen_chunk=1, last_seen_chunk=8)
    ally = graph_repo.upsert_entity(run_id=run_id, canonical_name="顾霜", first_seen_chunk=1, last_seen_chunk=8)
    rival = graph_repo.upsert_entity(run_id=run_id, canonical_name="谢危", first_seen_chunk=2, last_seen_chunk=8)

    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=ally.entity_id,
        relation_type="盟友",
        change_type="新建",
        chunk_id=3,
        evidence="并肩迎敌",
        confidence=0.92,
        source_relation_row_id=18001,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, hero.entity_id, ally.entity_id)
    graph_repo.refresh_entity_participants(run_id, [hero.entity_id, ally.entity_id])

    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=rival.entity_id,
        relation_type="敌对",
        change_type="新建",
        chunk_id=4,
        evidence="结下仇怨",
        confidence=0.58,
        source_relation_row_id=18002,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, hero.entity_id, rival.entity_id)
    graph_repo.refresh_entity_participants(run_id, [hero.entity_id, rival.entity_id])
    db_session.commit()

    service = KnowledgeGraphAuthorityService.from_session(db_session)
    view = service.build_graph_view(run_id)
    report = service.build_graph_report(run_id)

    assert report.summary.node_count == 3
    assert report.summary.edge_count == 2
    assert report.summary.density == 0.3333
    assert not hasattr(report.summary, "core_characters")
    assert report.quality.conflict_count == 0
    assert report.quality.low_confidence_count == 1
    assert len(view.relation_events) == 2


def test_build_graph_view_keeps_history_in_events_while_current_relations_stay_active_only(db_session) -> None:
    novel_id, run_id = _create_run_with_novel(db_session, title="Graph View Current vs History")

    graph_repo = GraphRepository(db_session)
    hero = graph_repo.upsert_entity(run_id=run_id, canonical_name="林渡", first_seen_chunk=1, last_seen_chunk=8)
    rival = graph_repo.upsert_entity(run_id=run_id, canonical_name="谢危", first_seen_chunk=2, last_seen_chunk=8)

    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=rival.entity_id,
        relation_type="敌对",
        change_type="新建",
        chunk_id=4,
        evidence="结下仇怨",
        confidence=0.58,
        source_relation_row_id=16001,
        directionality="directed",
    )
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=rival.entity_id,
        relation_type="敌对",
        change_type="断裂",
        chunk_id=8,
        evidence="恩怨了结",
        confidence=0.55,
        source_relation_row_id=16002,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, hero.entity_id, rival.entity_id)
    graph_repo.refresh_entity_participants(run_id, [hero.entity_id, rival.entity_id])
    db_session.commit()

    view = KnowledgeGraphAuthorityService.from_session(db_session).build_graph_view(run_id)

    assert view.confirmed_relations == []
    assert {(event.from_name, event.to_name, event.change_type) for event in view.relation_events} == {
        ("林渡", "谢危", "断裂"),
        ("林渡", "谢危", "新建"),
    }


def test_authority_dependency_matrix_constants_match_consumer_boundaries() -> None:
    assert set(LEVEL1_AUTHORITY_DEPENDENCY_FIELDS.keys()) == {
        "alias_mappings",
        "canonical_entities",
        "confirmed_relations",
        "entity_types",
    }
    assert set(TIMELINE_AUTHORITY_DEPENDENCY_FIELDS.keys()) == {
        "character_entities",
        "entity_lifecycles",
        "relation_events",
    }
    assert set(GRAPH_PAGE_AUTHORITY_DEPENDENCY_FIELDS.keys()) == {
        "participant_states",
        "confirmed_relations",
        "relation_events",
    }
    assert set(GRAPH_REPORT_AUTHORITY_DEPENDENCY_FIELDS.keys()) == {"summary", "quality"}
    assert set(EXPORT_GRAPH_AUTHORITY_DEPENDENCY_FIELDS.keys()) == {
        "canonical_entities",
        "current_relations",
        "relation_events",
    }


def test_authority_views_do_not_expose_other_consumers_shortcuts(db_session) -> None:
    novel_id, run_id = _create_run_with_novel(db_session, title="Authority Consumer Boundaries")

    graph_repo = GraphRepository(db_session)
    hero = graph_repo.upsert_entity(run_id=run_id, canonical_name="林渡", first_seen_chunk=1, last_seen_chunk=5)
    ally = graph_repo.upsert_entity(run_id=run_id, canonical_name="顾霜", first_seen_chunk=1, last_seen_chunk=5)
    graph_repo.insert_relation_event(
        run_id=run_id,
        from_entity_id=hero.entity_id,
        to_entity_id=ally.entity_id,
        relation_type="盟友",
        change_type="新建",
        chunk_id=3,
        evidence="并肩迎敌",
        confidence=0.82,
        source_relation_row_id=18101,
        directionality="directed",
    )
    graph_repo.refresh_current_relation(run_id, hero.entity_id, ally.entity_id)
    graph_repo.refresh_entity_participants(run_id, [hero.entity_id, ally.entity_id])
    db_session.commit()

    service = KnowledgeGraphAuthorityService.from_session(db_session)
    level1 = service.build_level1_snapshot(run_id)
    timeline = service.build_timeline_view(run_id)
    graph_view = service.build_graph_view(run_id)
    report = service.build_graph_report(run_id)

    assert not hasattr(level1, "relation_events")
    assert not hasattr(level1, "participant_states")
    assert not hasattr(timeline, "confirmed_relations")
    assert not hasattr(timeline, "participant_states")
    assert not hasattr(graph_view, "entity_lifecycles")
    assert not hasattr(graph_view, "summary")
    assert not hasattr(graph_view, "quality")
    assert not hasattr(report, "canonical_entities")
    assert not hasattr(report, "confirmed_relations")
    assert not hasattr(report, "relation_events")
