"""
娴嬭瘯瀹炰綋鐭ヨ瘑鍥捐氨鐩稿叧鎿嶄綔

淇敼鏃堕棿: 2026-03-15
淇敼鑰? TraeAI
浠诲姟: storage-layer-decoupling
淇敼鍐呭: 浣跨敤 SessionFactory 鏇夸唬 connect_db/create_tables锛屾秷闄?DeprecationWarning

淇敼鏃堕棿: 2026-03-15
淇敼鑰? TraeAI
浠诲姟: postgresql-migration
淇敼鍐呭: 鏇挎崲 sqlite_master 鏌ヨ涓?PostgreSQL information_schema 鏌ヨ锛屾坊鍔?analysis_runs 璁板綍鍒涘缓锛屼娇鐢ㄥ敮涓€ novel_id 閬垮厤鏁版嵁鍐茬獊

淇敼鏃堕棿: 2026-03-15
淇敼鑰? TraeAI
浠诲姟: postgresql-migration-cleanup
淇敼鍐呭: 鏀圭敤 PostgreSQL db_session fixture锛岀Щ闄?SQLite 渚濊禆
"""
import sys
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.storage.repositories import (
    EntityRepository,
    RunRepository,
)


class MockEmbeddingClient:
    def get_embedding(self, text: str):
        return [0.1] * 768


class TestEntityTables:
    def test_entities_table_exists(self, db_session):
        cursor = db_session.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'entities'")
        )
        assert cursor.fetchone() is not None

    def test_entity_aliases_table_exists(self, db_session):
        cursor = db_session.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'entity_aliases'")
        )
        assert cursor.fetchone() is not None

    def test_entity_relations_table_exists(self, db_session):
        cursor = db_session.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'entity_relations'")
        )
        assert cursor.fetchone() is not None

    def test_entity_snapshots_table_exists(self, db_session):
        cursor = db_session.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'entity_snapshots'")
        )
        assert cursor.fetchone() is not None

    def test_idx_entity_aliases_alias_exists(self, db_session):
        cursor = db_session.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_entity_aliases_alias'")
        )
        assert cursor.fetchone() is not None

    def test_idx_entity_snapshots_novel_chunk_exists(self, db_session):
        cursor = db_session.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_entity_snapshots_novel_chunk'")
        )
        assert cursor.fetchone() is not None


class TestEntityOperations:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.entity_repo = EntityRepository(db_session)
        self.novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def test_insert_entity(self):
        entity_id = self.entity_repo.insert_entity(
            novel_id=self.novel_id,
            canonical="鏉庣巹",
            entity_type="character",
            first_chunk=1,
            description="青云宗弟子",
            confidence=0.95,
            run_id=self.run_id,
        )
        assert entity_id > 0

    def test_fetch_entity_by_canonical(self):
        self.entity_repo.insert_entity(
            novel_id=self.novel_id,
            canonical="鏉庣巹",
            entity_type="character",
            first_chunk=1,
            description="青云宗弟子",
            run_id=self.run_id,
        )
        entity = self.entity_repo.fetch_entity_by_canonical(self.novel_id, "鏉庣巹", self.run_id)
        assert entity is not None
        assert entity["canonical"] == "鏉庣巹"
        assert entity["entity_type"] == "character"

    def test_update_entity_last_chunk(self):
        entity_id = self.entity_repo.insert_entity(
            novel_id=self.novel_id,
            canonical="鏉庣巹",
            entity_type="character",
            first_chunk=1,
            run_id=self.run_id,
        )
        self.entity_repo.update_entity_last_chunk(entity_id, 10)
        entity = self.entity_repo.fetch_entity_by_canonical(self.novel_id, "鏉庣巹", self.run_id)
        assert entity["last_chunk"] == 10

    def test_insert_entity_embedding(self):
        entity_id = self.entity_repo.insert_entity(
            novel_id=self.novel_id,
            canonical="鏉庣巹",
            entity_type="character",
            run_id=self.run_id,
        )
        embedding = [0.1] * 1536
        self.entity_repo.insert_entity_embedding(entity_id, embedding)
        entity = self.entity_repo.fetch_entity_by_canonical(self.novel_id, "鏉庣巹", self.run_id)
        assert entity["entity_id"] == entity_id

    def test_entity_unique_key_is_run_scoped(self):
        from src.storage.models.entity import Entity

        unique_constraints = [
            constraint
            for constraint in Entity.__table__.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        ]
        target = next(
            c for c in unique_constraints if c.name == "uq_entities_novel_run_canonical"
        )
        column_names = [col.name for col in target.columns]
        assert column_names == ["novel_id", "run_id", "canonical"]


class TestAliasOperations:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.entity_repo = EntityRepository(db_session)
        self.novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

        self.entity_id = self.entity_repo.insert_entity(
            novel_id=self.novel_id,
            canonical="鏉庣巹",
            entity_type="character",
            run_id=self.run_id,
        )

    def test_insert_entity_alias(self):
        alias_id = self.entity_repo.insert_entity_alias(
            entity_id=self.entity_id,
            alias="閭ｄ汉",
            run_id=self.run_id,
            alias_type="pronoun",
            source_chunk=5,
        )
        assert alias_id > 0

    def test_fetch_entity_by_alias(self):
        self.entity_repo.insert_entity_alias(
            entity_id=self.entity_id,
            alias="閭ｄ汉",
            run_id=self.run_id,
            alias_type="pronoun",
        )
        entity = self.entity_repo.fetch_entity_by_alias(self.novel_id, "閭ｄ汉", self.run_id)
        assert entity is not None
        assert entity["canonical"] == "鏉庣巹"

    def test_increment_alias_confirm(self):
        self.entity_repo.insert_entity_alias(
            entity_id=self.entity_id,
            alias="閭ｄ汉",
            run_id=self.run_id,
        )
        self.entity_repo.increment_alias_confirm(self.entity_id, "閭ｄ汉")
        entity = self.entity_repo.fetch_entity_by_alias(self.novel_id, "閭ｄ汉", self.run_id)
        assert entity["confirm_count"] == 2

    def test_fetch_all_aliases_for_entity(self):
        self.entity_repo.insert_entity_alias(self.entity_id, "閭ｄ汉", self.run_id, "pronoun")
        self.entity_repo.insert_entity_alias(self.entity_id, "鍓嶈緢", self.run_id, "title")
        aliases = self.entity_repo.fetch_all_aliases_for_entity(self.entity_id)
        assert len(aliases) == 2


class TestRelationOperations:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.entity_repo = EntityRepository(db_session)
        self.novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

        self.entity1_id = self.entity_repo.insert_entity(
            novel_id=self.novel_id,
            canonical="鏉庣巹",
            entity_type="character",
            run_id=self.run_id,
        )
        self.entity2_id = self.entity_repo.insert_entity(
            novel_id=self.novel_id,
            canonical="闄堝嘲",
            entity_type="character",
            run_id=self.run_id,
        )

    def test_insert_entity_relation(self):
        rel_id = self.entity_repo.insert_entity_relation(
            novel_id=self.novel_id,
            from_entity=self.entity1_id,
            to_entity=self.entity2_id,
            rel_type="鐩熷弸",
            first_chunk=1,
            tension=0.5,
            run_id=self.run_id,
        )
        assert rel_id > 0

    def test_fetch_relations_for_entity(self):
        self.entity_repo.insert_entity_relation(
            novel_id=self.novel_id,
            from_entity=self.entity1_id,
            to_entity=self.entity2_id,
            rel_type="鐩熷弸",
            run_id=self.run_id,
        )
        relations = self.entity_repo.fetch_relations_for_entity(self.entity1_id, self.novel_id, self.run_id)
        assert len(relations) == 1
        assert relations[0]["rel_type"] == "鐩熷弸"

    def test_update_relation_last_chunk(self):
        rel_id = self.entity_repo.insert_entity_relation(
            novel_id=self.novel_id,
            from_entity=self.entity1_id,
            to_entity=self.entity2_id,
            rel_type="鐩熷弸",
            first_chunk=1,
            run_id=self.run_id,
        )
        self.entity_repo.update_relation_last_chunk(rel_id, 20)
        relations = self.entity_repo.fetch_relations_for_entity(self.entity1_id, self.novel_id, self.run_id)
        assert relations[0]["last_chunk"] == 20

    def test_fetch_active_relations(self):
        self.entity_repo.insert_entity_relation(
            novel_id=self.novel_id,
            from_entity=self.entity1_id,
            to_entity=self.entity2_id,
            rel_type="鐩熷弸",
            run_id=self.run_id,
        )
        relations = self.entity_repo.fetch_active_relations(self.novel_id, self.entity1_id, self.run_id)
        assert len(relations) == 1


class TestSnapshotOperations:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.entity_repo = EntityRepository(db_session)
        self.novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

        self.entity_id = self.entity_repo.insert_entity(
            novel_id=self.novel_id,
            canonical="鏉庣巹",
            entity_type="character",
            run_id=self.run_id,
        )

    def test_insert_entity_snapshot(self):
        state = {"emotion_score": -0.3, "location": "青云城"}
        snap_id = self.entity_repo.insert_entity_snapshot(
            novel_id=self.novel_id,
            entity_id=self.entity_id,
            chunk_id=1,
            state_json=json.dumps(state, ensure_ascii=False),
            run_id=self.run_id,
        )
        assert snap_id > 0

    def test_fetch_snapshots_by_chunk(self):
        state = {"emotion_score": -0.3}
        self.entity_repo.insert_entity_snapshot(
            novel_id=self.novel_id,
            entity_id=self.entity_id,
            chunk_id=5,
            state_json=json.dumps(state, ensure_ascii=False),
            run_id=self.run_id,
        )
        snapshots = self.entity_repo.fetch_snapshots_by_chunk(self.novel_id, 1, 10, self.run_id)
        assert len(snapshots) == 1

    def test_fetch_recent_snapshots(self):
        for i in range(5):
            self.entity_repo.insert_entity_snapshot(
                novel_id=self.novel_id,
                entity_id=self.entity_id,
                chunk_id=i,
                state_json="{}",
                run_id=self.run_id,
            )
        snapshots = self.entity_repo.fetch_recent_snapshots(self.novel_id, self.run_id, limit=3)
        assert len(snapshots) == 3
        assert snapshots[0]["chunk_id"] == 4


