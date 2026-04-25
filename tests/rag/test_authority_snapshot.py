from __future__ import annotations

import uuid

from src.chunking.chunker import Chunk
from src.rag import Level1AuthorityProvider, NarrativeEvidenceService
from src.rag.evidence_contracts import EvidenceRequest
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


class TestLevel1AuthoritySnapshot:
    def test_build_snapshot_includes_aliases_entities_relations_and_entity_types(self, db_session) -> None:
        novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, novel_id)
        run_id = RunRepository(db_session).create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chunk_repo = ChunkRepository(db_session)
        chunk_repo.insert_chunks(run_id, [
            Chunk(index=1, text="测试1", start=0, end=100),
            Chunk(index=2, text="测试2", start=100, end=200),
            Chunk(index=8, text="测试8", start=800, end=900),
        ])
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
            (item.from_name, item.to_name, item.relation_type, item.is_active) for item in snapshot.confirmed_relations
        }
        assert ("方源", "白凝冰", "盟友", True) in relations

    def test_build_snapshot_excludes_inactive_current_relations(self, db_session) -> None:
        novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, novel_id)
        run_id = RunRepository(db_session).create_run(
            novel_id=novel_id,
            source_path="test",
            title="Test Novel",
        )
        chunk_repo = ChunkRepository(db_session)
        chunk_repo.insert_chunks(run_id, [
            Chunk(index=1, text="测试1", start=0, end=100),
            Chunk(index=3, text="测试3", start=300, end=400),
            Chunk(index=9, text="测试9", start=900, end=1000),
        ])
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

    def test_collect_evidence_level2_uses_authority_contract_instead_of_raw_graph_rows(self, db_session) -> None:
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
            canonical_name="白芷",
            entity_type="organization",
            last_seen_chunk=12,
            primary_role_function="helper",
            last_action="观察",
            last_emotion_score="平静",
            status="active",
        )
        db_session.commit()

        provider = NarrativeEvidenceService(
            graph_repo=graph_repo,
            novel_id=novel_id,
            run_id=run_id,
            lookback_chunks=5,
            level1_enabled=False,
            level2_enabled=True,
            level3_enabled=False,
        )

        bundle = provider._collect_base_evidence(
            EvidenceRequest(
                consumer="annotation_phase1",
                objective="identity",
                query_text="",
                requested_names=[],
                seed_entities=[],
                background_entities=[],
                current_chunk=12,
                max_chunk_id=11,
                exclude_chunk_ids=[12],
                need_level1=False,
                need_level2=True,
                need_level3=False,
                allow_llm_query_expansion=False,
                top_k=5,
                max_queries=1,
                model_rerank_query_max_chars=0,
            )
        )

        assert len(bundle.local_evidence) == 1
        metadata = bundle.local_evidence[0].metadata
        assert metadata["name"] == "白芷"
        assert metadata["entity_type"] == "organization"
        assert metadata["recent_action"] == "观察"
        assert metadata["recent_emotion"] == "平静"
        assert "last_action" not in metadata
        assert "last_emotion" not in metadata
