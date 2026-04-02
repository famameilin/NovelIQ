"""GraphRepository 单元测试。"""

from __future__ import annotations

import uuid

from src.storage.repositories import GraphRepository, RunRepository


class TestGraphAliasMap:
    def test_fetch_alias_map_contains_canonical_self_mapping(self, db_session) -> None:
        novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
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
        novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
        run_id = RunRepository(db_session).create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
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
        assert conflicts[0]["relation_types"] == ["敌对", "盟友"]

    def test_fetch_low_confidence_relation_events_filters_by_threshold(self, db_session) -> None:
        novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
        run_id = RunRepository(db_session).create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
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
        assert float(low_conf[0]["confidence"]) == 0.31


class TestFetchEntitiesWithStatus:
    def test_fetch_entities_filters_by_status_active(self, db_session) -> None:
        novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
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
