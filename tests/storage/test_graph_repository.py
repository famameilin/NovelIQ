"""GraphRepository 单元测试。"""

from __future__ import annotations

import uuid

from src.storage.repositories import EntityRepository, GraphRepository, RunRepository


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


class TestGraphLegacySync:
    def test_sync_entity_aliases_to_legacy_creates_entity_and_alias(self, db_session) -> None:
        novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
        run_id = RunRepository(db_session).create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )

        graph_repo = GraphRepository(db_session)
        entity = graph_repo.upsert_entity(
            run_id=run_id,
            canonical_name="陈峰",
            entity_type="character",
            first_seen_chunk=2,
            last_seen_chunk=7,
            source_confidence=0.88,
        )
        graph_repo.upsert_alias(
            run_id=run_id,
            entity_id=entity.entity_id,
            alias="阿峰",
            source_chunk_id=3,
            evidence="对话",
            confidence=0.8,
            source_type="nickname",
        )

        graph_repo.sync_entity_aliases_to_legacy(run_id=run_id, novel_id=novel_id)

        entity_repo = EntityRepository(db_session)
        legacy_entity = entity_repo.fetch_entity_by_canonical(novel_id, "陈峰", run_id)
        assert legacy_entity is not None
        assert legacy_entity["first_chunk"] == 2
        assert legacy_entity["last_chunk"] == 7

        aliases = entity_repo.fetch_all_aliases_for_entity(legacy_entity["entity_id"], run_id)
        assert any(alias["alias"] == "阿峰" for alias in aliases)

    def test_sync_entity_aliases_to_legacy_updates_existing_first_chunk(self, db_session) -> None:
        novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
        run_id = RunRepository(db_session).create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )

        entity_repo = EntityRepository(db_session)
        entity_id = entity_repo.insert_entity(
            novel_id=novel_id,
            canonical="白洛",
            entity_type="character",
            first_chunk=99,
            run_id=run_id,
        )
        assert entity_id is not None
        entity_repo.update_entity_last_chunk(entity_id, 100)


        graph_repo = GraphRepository(db_session)
        graph_repo.upsert_entity(
            run_id=run_id,
            canonical_name="白洛",
            first_seen_chunk=4,
            last_seen_chunk=12,
        )

        graph_repo.sync_entity_aliases_to_legacy(run_id=run_id, novel_id=novel_id)

        updated = entity_repo.fetch_entity_by_canonical(novel_id, "白洛", run_id)
        assert updated is not None
        assert updated["first_chunk"] == 4
        assert updated["last_chunk"] == 12
