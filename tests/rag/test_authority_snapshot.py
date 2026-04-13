from __future__ import annotations

import uuid

from src.rag import Level1AuthorityProvider
from src.storage.repositories import GraphRepository, RunRepository


class TestLevel1AuthoritySnapshot:
    def test_build_snapshot_includes_aliases_entities_relations_and_entity_types(self, db_session) -> None:
        novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
        run_id = RunRepository(db_session).create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )

        graph_repo = GraphRepository(db_session)
        fang_yuan = graph_repo.upsert_entity(
            run_id=run_id,
            canonical_name="方源",
            entity_type="character",
            first_seen_chunk=1,
            last_seen_chunk=10,
        )
        bai_ning_bing = graph_repo.upsert_entity(
            run_id=run_id,
            canonical_name="白凝冰",
            entity_type="character",
            first_seen_chunk=2,
            last_seen_chunk=12,
        )
        graph_repo.upsert_alias(
            run_id=run_id,
            entity_id=fang_yuan.entity_id,
            alias="古月方源",
            source_chunk_id=1,
            evidence="自报名号",
            confidence=0.98,
            source_type="named",
        )
        graph_repo.insert_relation_event(
            run_id=run_id,
            from_entity_id=fang_yuan.entity_id,
            to_entity_id=bai_ning_bing.entity_id,
            relation_type="盟友",
            change_type="新建",
            chunk_id=8,
            evidence="并肩作战",
            confidence=0.93,
            source_relation_row_id=9001,
            directionality="directed",
        )
        graph_repo.refresh_current_relation(run_id, fang_yuan.entity_id, bai_ning_bing.entity_id)
        db_session.commit()

        snapshot = Level1AuthorityProvider(graph_repo).build_snapshot(run_id)

        alias_pairs = {(item.alias, item.canonical) for item in snapshot.alias_mappings}
        assert ("古月方源", "方源") in alias_pairs
        assert ("方源", "方源") in alias_pairs

        canonical_names = {item.name for item in snapshot.canonical_entities}
        assert canonical_names == {"方源", "白凝冰"}

        entity_types = {item.name: item.entity_type for item in snapshot.entity_types}
        assert entity_types == {"方源": "character", "白凝冰": "character"}

        relations = {
            (item.from_name, item.to_name, item.relation_type, item.is_active)
            for item in snapshot.confirmed_relations
        }
        assert ("方源", "白凝冰", "盟友", True) in relations

    def test_build_snapshot_excludes_inactive_current_relations(self, db_session) -> None:
        novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
        run_id = RunRepository(db_session).create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )

        graph_repo = GraphRepository(db_session)
        han_li = graph_repo.upsert_entity(run_id=run_id, canonical_name="韩立", first_seen_chunk=1, last_seen_chunk=9)
        nan_gong = graph_repo.upsert_entity(
            run_id=run_id,
            canonical_name="南宫婉",
            first_seen_chunk=1,
            last_seen_chunk=9,
        )
        graph_repo.insert_relation_event(
            run_id=run_id,
            from_entity_id=han_li.entity_id,
            to_entity_id=nan_gong.entity_id,
            relation_type="爱慕",
            change_type="新建",
            chunk_id=3,
            evidence="初见倾心",
            confidence=0.8,
            source_relation_row_id=9101,
            directionality="directed",
        )
        graph_repo.insert_relation_event(
            run_id=run_id,
            from_entity_id=han_li.entity_id,
            to_entity_id=nan_gong.entity_id,
            relation_type="爱慕",
            change_type="断裂",
            chunk_id=9,
            evidence="关系断裂",
            confidence=0.7,
            source_relation_row_id=9102,
            directionality="directed",
        )
        graph_repo.refresh_current_relation(run_id, han_li.entity_id, nan_gong.entity_id)
        db_session.commit()

        snapshot = Level1AuthorityProvider(graph_repo).build_snapshot(run_id)

        assert snapshot.confirmed_relations == []

    def test_build_active_entity_contexts_expose_level2_contract(self, db_session) -> None:
        novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"
        run_id = RunRepository(db_session).create_run(
            novel_id=novel_id,
            source_path="test",
            title="Active Entity Context",
        )

        graph_repo = GraphRepository(db_session)
        graph_repo.upsert_entity(
            run_id=run_id,
            canonical_name="白芷",
            entity_type="character",
            last_seen_chunk=8,
            primary_role_function="helper",
            last_action="观察局势",
            last_emotion_score="警惕",
            status="active",
        )
        db_session.commit()

        contexts = Level1AuthorityProvider(graph_repo).build_active_entity_contexts(
            run_id,
            current_chunk=8,
            lookback=3,
        )

        assert len(contexts) == 1
        assert contexts[0].name == "白芷"
        assert contexts[0].recent_action == "观察局势"
        assert contexts[0].recent_emotion == "警惕"
        assert contexts[0].last_seen_chunk == 8
