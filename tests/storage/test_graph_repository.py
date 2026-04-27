"""GraphRepository 单元测试。"""

from __future__ import annotations

import uuid

from src.chunking.chunker import Chunk
from src.storage.repositories import ChunkRepository, GraphRepository, RunRepository


def _insert_test_novel(db_session, novel_id: str) -> None:
    """
    创建测试用 Novel 记录，避免 create_run 时 ForeignKeyViolation。

    创建时间: 2026-04-23
    任务: 修复 pytest ForeignKeyViolation
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


class TestGraphAliasMap:
    def test_fetch_alias_map_contains_canonical_self_mapping(self, db_session) -> None:
        novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, novel_id)
        run_id = RunRepository(db_session).create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )

        graph_repo = GraphRepository(db_session)
        entity = graph_repo.upsert_entity(
            run_id=run_id,
            canonical_name="李玄",
            first_seen_chunk=1,
            last_seen_chunk=1,
        )
        graph_repo.upsert_alias(
            run_id=run_id,
            entity_id=entity.entity_id,
            alias="那人",
            source_chunk_id=1,
            evidence="称呼",
            confidence=0.9,
            source_type="pronoun",
        )

        alias_map = graph_repo.fetch_alias_map(run_id)

        assert alias_map["那人"] == "李玄"
        assert alias_map["李玄"] == "李玄"


class TestGraphQualitySignals:
    def test_detect_relation_conflicts_finds_bidirectional_type_mismatch(self, db_session) -> None:
        novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, novel_id)
        run_id = RunRepository(db_session).create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chunk_repo = ChunkRepository(db_session)
        chunk_repo.insert_chunks(run_id, [
            Chunk(index=10, text="测试10", start=1000, end=1100),
            Chunk(index=11, text="测试11", start=1100, end=1200),
        ])
        graph_repo = GraphRepository(db_session)
        a = graph_repo.upsert_entity(run_id=run_id, canonical_name="方源", first_seen_chunk=1, last_seen_chunk=1)
        b = graph_repo.upsert_entity(run_id=run_id, canonical_name="白凝冰", first_seen_chunk=1, last_seen_chunk=1)

        graph_repo.insert_relation_event(
            run_id=run_id,
            from_entity_id=a.entity_id,
            to_entity_id=b.entity_id,
            relation_type="盟友",
            change_type="新建",
            chunk_id=10,
            evidence="并肩作战",
            confidence=0.92,
            source_relation_row_id=1001,
            directionality="directed",
        )
        graph_repo.insert_relation_event(
            run_id=run_id,
            from_entity_id=b.entity_id,
            to_entity_id=a.entity_id,
            relation_type="敌对",
            change_type="新建",
            chunk_id=11,
            evidence="反目成仇",
            confidence=0.87,
            source_relation_row_id=1002,
            directionality="directed",
        )
        graph_repo.refresh_current_relation(run_id, a.entity_id, b.entity_id)
        graph_repo.refresh_current_relation(run_id, b.entity_id, a.entity_id)
        db_session.commit()

        conflicts = graph_repo.detect_relation_conflicts(run_id, active_only=True)
        assert len(conflicts) == 1
        assert conflicts[0].relation_types == ["敌对", "盟友"]

    def test_fetch_low_confidence_relation_events_filters_by_threshold(self, db_session) -> None:
        novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, novel_id)
        run_id = RunRepository(db_session).create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chunk_repo = ChunkRepository(db_session)
        chunk_repo.insert_chunks(run_id, [
            Chunk(index=8, text="测试8", start=800, end=900),
            Chunk(index=9, text="测试9", start=900, end=1000),
        ])
        graph_repo = GraphRepository(db_session)
        a = graph_repo.upsert_entity(run_id=run_id, canonical_name="韩立", first_seen_chunk=1, last_seen_chunk=1)
        b = graph_repo.upsert_entity(run_id=run_id, canonical_name="南宫婉", first_seen_chunk=1, last_seen_chunk=1)

        graph_repo.insert_relation_event(
            run_id=run_id,
            from_entity_id=a.entity_id,
            to_entity_id=b.entity_id,
            relation_type="爱慕",
            change_type="新建",
            chunk_id=8,
            evidence="低置信度样本",
            confidence=0.31,
            source_relation_row_id=2001,
            directionality="directed",
        )
        graph_repo.insert_relation_event(
            run_id=run_id,
            from_entity_id=b.entity_id,
            to_entity_id=a.entity_id,
            relation_type="盟友",
            change_type="新建",
            chunk_id=9,
            evidence="高置信度样本",
            confidence=0.95,
            source_relation_row_id=2002,
            directionality="directed",
        )
        db_session.commit()

        low_conf = graph_repo.fetch_low_confidence_relation_events(run_id, threshold=0.6)
        assert len(low_conf) == 1
        assert float(low_conf[0].confidence) == 0.31


class TestFetchEntitiesWithStatus:
    def test_fetch_entities_filters_by_status_active(self, db_session) -> None:
        novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, novel_id)
        run_id = RunRepository(db_session).create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        graph_repo = GraphRepository(db_session)
        graph_repo.upsert_entity(
            run_id=run_id,
            canonical_name="方源",
            first_seen_chunk=1,
            last_seen_chunk=5,
            status="active",
        )
        graph_repo.upsert_entity(
            run_id=run_id,
            canonical_name="韩立",
            first_seen_chunk=1,
            last_seen_chunk=10,
            status="merged",
        )
        db_session.commit()

        active_entities = graph_repo.fetch_entities(run_id, status="active")
        assert len(active_entities) == 1
        assert active_entities[0].canonical_name == "方源"

        all_entities = graph_repo.fetch_entities(run_id)
        assert len(all_entities) == 2


class TestGraphParticipants:
    def test_refresh_entity_participants_tracks_relation_metrics(self, db_session) -> None:
        novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, novel_id)
        run_id = RunRepository(db_session).create_run(
            novel_id=novel_id,
            source_path="test",
            title="Participant Metrics",
        )
        chunk_repo = ChunkRepository(db_session)
        chunk_repo.insert_chunks(
            run_id,
            [
                Chunk(index=3, text="测试3", start=300, end=400),
                Chunk(index=4, text="测试4", start=400, end=500),
            ],
        )

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
            source_relation_row_id=3001,
            directionality="directed",
        )
        graph_repo.insert_relation_event(
            run_id=run_id,
            from_entity_id=hero.entity_id,
            to_entity_id=rival.entity_id,
            relation_type="敌对",
            change_type="新建",
            chunk_id=4,
            evidence="结下仇怨",
            confidence=0.58,
            source_relation_row_id=3002,
            directionality="directed",
        )
        graph_repo.refresh_current_relation(run_id, hero.entity_id, ally.entity_id)
        graph_repo.refresh_current_relation(run_id, hero.entity_id, rival.entity_id)
        graph_repo.refresh_entity_participants(run_id, [hero.entity_id, ally.entity_id, rival.entity_id])
        db_session.commit()

        participants = {item.name: item for item in graph_repo.fetch_participant_entities(run_id)}

        assert set(participants.keys()) == {"林渡", "顾霜", "谢危"}
        assert participants["林渡"].relation_event_count == 2
        assert participants["林渡"].current_degree == 2
        assert participants["林渡"].historical_degree == 2
        assert participants["林渡"].first_relation_chunk == 3
        assert participants["林渡"].last_relation_chunk == 4
        assert participants["林渡"].latest_relation_event_id is not None
        assert participants["顾霜"].relation_event_count == 1
        assert participants["顾霜"].current_degree == 1
        assert participants["顾霜"].historical_degree == 1

    def test_reset_graph_tables_clears_participant_projection(self, db_session) -> None:
        novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, novel_id)
        run_id = RunRepository(db_session).create_run(
            novel_id=novel_id,
            source_path="test",
            title="Participant Reset",
        )
        chunk_repo = ChunkRepository(db_session)
        chunk_repo.insert_chunks(run_id, [Chunk(index=5, text="测试5", start=500, end=600)])

        graph_repo = GraphRepository(db_session)
        hero = graph_repo.upsert_entity(run_id=run_id, canonical_name="林渡", first_seen_chunk=1, last_seen_chunk=8)
        ally = graph_repo.upsert_entity(run_id=run_id, canonical_name="顾霜", first_seen_chunk=1, last_seen_chunk=8)
        graph_repo.insert_relation_event(
            run_id=run_id,
            from_entity_id=hero.entity_id,
            to_entity_id=ally.entity_id,
            relation_type="盟友",
            change_type="新建",
            chunk_id=5,
            evidence="并肩迎敌",
            confidence=0.92,
            source_relation_row_id=5001,
            directionality="directed",
        )
        graph_repo.refresh_current_relation(run_id, hero.entity_id, ally.entity_id)
        graph_repo.refresh_entity_participants(run_id, [hero.entity_id, ally.entity_id])
        db_session.commit()

        assert graph_repo.count_entity_participants(run_id) == 2

        graph_repo.reset_graph_tables(run_id)
        db_session.commit()

        assert graph_repo.count_entity_participants(run_id) == 0
        assert graph_repo.fetch_entities(run_id) == []
        assert graph_repo.count_relation_events(run_id) == 0
