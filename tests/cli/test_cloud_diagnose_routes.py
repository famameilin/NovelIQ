"""
云端诊断路由测试

创建时间: 2025-03-11
创建者: TraeAI
任务: 测试云端诊断

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 使用 SessionFactory 替代 connect_db/create_tables，消除 DeprecationWarning

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 使用 SQLAlchemy text() 替换 ? 占位符，移除 sqlite3 导入

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration-cleanup
修改内容: 改用 PostgreSQL db_session fixture，移除 SessionFactory 依赖

修改时间: 2026-03-27
修改者: TraeAI
任务: 简化 diagnosis payload
修改内容: 移除 common_character_names 相关测试断言

修改时间: 2026-03-29
修改者: TraeAI
任务: refactor-phase1-identity-extraction
修改内容: 移除 relations 字段相关测试
"""

import json
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from conftest import FakeClient

from src.chunking.chunker import Chunk
from src.models.cloud import build_diagnosis_payload
from src.models.cloud.schema import CloudAnalysis
from src.models.diagnosis import DiagnosisClient
from src.models.local.schema import (
    CharacterSnapshot,
    ChunkAnnotation,
)
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    ChunkStyleData,
    DiagnosisRepository,
    RunRepository,
    StatsRepository,
)
from src.workflows.diagnose import run_diagnose


class TestCloudDiagnose:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def _create_full_data(self, chunk_count: int = 5) -> None:
        chunk_repo = ChunkRepository(self.db_session)
        chunks = [
            Chunk(index=i, start=0, end=100, text=f"这是第{i}个测试文本，包含一些内容。") for i in range(chunk_count)
        ]
        chunk_repo.insert_chunks(self.run_id, chunks)

        style_rows = [
            ChunkStyleData(
                chunk_id=i,
                mtld=50.0 + i,
                ttr=0.5,
                avg_sent_len=20.0 + i,
                sent_len_std=5.0,
                d_value=5.0,
                pause_density=0.1,
                fight_density=0.0,
                exclaim_density=0.0,
                dialogue_ratio=0.2,
                question_density=0.0,
                sensory_density=0.0,
                metaphor_density=0.0,
                function_word_vector="{}",
                category_density_combat=0.0,
                category_density_body=0.0,
                category_density_relation=0.0,
                category_density_faction=0.0,
                category_density_command=0.0,
                category_density_action=0.0,
                category_density_psychology=0.0,
                category_density_measure=0.0,
                category_density_emotion=0.0,
                category_density_color=0.0,
            )
            for i in range(chunk_count)
        ]
        chunk_repo.insert_chunk_style(self.run_id, style_rows)

        for i in range(chunk_count):
            self.db_session.execute(
                text(
                    "INSERT INTO emotion_curve (chunk_id, pos_density, neg_density, net_density, smoothed_density, run_id) VALUES (:chunk_id, :pos, :neg, :net, :smoothed, :run_id)"
                ),
                {
                    "chunk_id": i,
                    "pos": 0.1,
                    "neg": 0.05,
                    "net": 0.05 + i * 0.01,
                    "smoothed": 0.05,
                    "run_id": self.run_id,
                },
            )
            self.db_session.execute(
                text(
                    "INSERT INTO rhythm_curve (chunk_id, tension_proxy, tension_composite, run_id) VALUES (:chunk_id, :proxy, :composite, :run_id)"
                ),
                {"chunk_id": i, "proxy": 0.5, "composite": 0.5, "run_id": self.run_id},
            )

        ann_repo = AnnotationRepository(self.db_session)
        for i in range(chunk_count):
            annotation = ChunkAnnotation(
                emotional_valence="mild_positive" if i % 2 == 0 else "mild_negative",
                event_type="高潮" if i in [1, 2] else ("转折" if i == 3 else "铺垫"),
                pivot_moment=(i in [1, 2]),
                cliffhanger=(i == chunk_count - 1),
                has_foreshadowing=(i == 0),
                foreshadowing_type="causal" if i == 0 else None,
                foreshadowing_desc="测试伏笔" if i == 0 else "",
                characters=[
                    CharacterSnapshot(
                        name=f"角色{i}",
                        role_function="主体" if i == 0 else "其他",
                        action="测试行为",
                        action_type="其他",
                        emotion_score="neutral",
                    )
                ],
                dialogues=[],
            )
            ann_repo.insert_chunk_annotation(self.run_id, i, annotation)
            ann_repo.insert_chunk_characters(self.run_id, i, annotation.characters)

        self.db_session.commit()

    def test_build_diagnosis_payload(self) -> None:
        """
        修改时间: 2026-03-19
        修改者: TraeAI
        任务: 修复run_id过滤BUG
        修改内容: 添加run_id参数

        修改时间: 2026-03-27
        修改者: TraeAI
        任务: 简化 diagnosis payload
        修改内容: 移除不存在的 display_name_map 参数
        """
        self._create_full_data(5)
        state_payload = {
            "discovered_names": ["角色0", "伯安"],
            "known_canonical_names": ["伯安"],
            "alias_merges": [["角色0", "伯安"]],
            "review_status": [],
            "pending_relations": [],
            "version": 1,
            "created_at": 1.0,
            "updated_at": 1.0,
        }
        self.db_session.execute(
            text(
                """
                INSERT INTO disambig_checkpoint (run_id, alias_map, updated_at, entity_relations, disambig_states)
                VALUES (:run_id, :alias_map, :updated_at, :entity_relations, :disambig_states)
                """
            ),
            {
                "run_id": self.run_id,
                "alias_map": json.dumps(state_payload, ensure_ascii=False),
                "updated_at": 1.0,
                "entity_relations": None,
                "disambig_states": None,
            },
        )
        self.db_session.commit()

        payload = build_diagnosis_payload(self.db_session, self.novel_id, self.run_id)

        assert payload["novel_id"] == self.novel_id
        assert "pivot_blocks" in payload
        assert "pivot_moments" in payload
        assert "high_tension_paragraphs" in payload
        assert "character_relations" in payload
        assert "foreshadowing_list" in payload
        assert "first_chapter_summary" in payload
        assert "last_chapter_summary" in payload
        assert "known_characters" in payload
        assert "alias_merges" in payload
        assert "graph_summary" in payload

        assert len(payload["pivot_blocks"]) > 0
        assert len(payload["pivot_moments"]) > 0
        assert len(payload["foreshadowing_list"]) > 0
        assert payload["known_characters"] == ["伯安"]
        assert payload["alias_merges"] == {"角色0": "伯安"}
        assert "quality" in payload["graph_summary"]
        assert "conflict_count" in payload["graph_summary"]["quality"]
        assert "low_confidence_count" in payload["graph_summary"]["quality"]

    def test_fetch_pivot_blocks(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        blocks = diag_repo.fetch_pivot_blocks(self.run_id)
        assert len(blocks) > 0
        for block in blocks:
            assert len(block) == 3

    def test_fetch_high_tension_chunks(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        chunks = diag_repo.fetch_high_tension_chunks(self.run_id, limit=3)
        assert len(chunks) > 0
        for chunk in chunks:
            assert len(chunk) == 3

    def test_fetch_relation_changes(self) -> None:
        """
        测试获取关系变更记录

        修改时间: 2026-03-29
        修改者: TraeAI
        任务: refactor-phase1-identity-extraction
        修改内容: relations 字段已移除，此测试应返回空列表
        """
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        relations = diag_repo.fetch_relation_changes(self.run_id)
        # relations 字段已从 ChunkAnnotation 移除，所以返回空列表
        assert len(relations) == 0

    def test_fetch_foreshadowing_chunks(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        chunks = diag_repo.fetch_foreshadowing_chunks(self.run_id)
        assert len(chunks) > 0

    def test_fetch_first_last_chunk_summary(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        first, last = diag_repo.fetch_first_last_chunk_summary(self.run_id)
        assert len(first) > 0
        assert len(last) > 0

    def test_fetch_pivot_moments(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        moments = diag_repo.fetch_pivot_moments(self.run_id)
        assert len(moments) > 0

    def test_run_diagnose_with_cloud(self) -> None:
        self._create_full_data(5)

        analysis = run_diagnose(
            run_id=self.run_id,
            session=self.db_session,
            client=FakeClient(),
        )
        assert analysis is not None
        assert analysis.narrative_type == "三幕"
        assert analysis.foreshadow_rate == 0.1

        rows = self.db_session.execute(
            text("SELECT COUNT(*) FROM cloud_analysis WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        assert rows > 0

    def test_run_diagnose_persists_result(self) -> None:
        self._create_full_data(3)

        run_diagnose(
            run_id=self.run_id,
            session=self.db_session,
            client=FakeClient(),
        )
        rows = self.db_session.execute(
            text(
                "SELECT novel_id, narrative_type, foreshadow_rate, narrative_arc_type, protagonist, main_characters, core_cast "
                "FROM cloud_analysis WHERE run_id = :run_id"
            ),
            {"run_id": self.run_id},
        ).fetchall()
        assert len(rows) > 0
        assert rows[0][3] == "白手起家"
        assert rows[0][4] == "角色0"
        assert "角色0" in rows[0][5]
        assert "角色1" in rows[0][6]

        stats_repo = StatsRepository(self.db_session)
        fetched = stats_repo.fetch_cloud_analysis(self.novel_id, self.run_id)
        assert fetched is not None
        assert fetched["protagonist"] == "角色0"
        assert fetched["main_characters"] is not None
        assert fetched["core_cast"] is not None

    def test_finalize_result_preserves_character_fields(self) -> None:
        client = object.__new__(DiagnosisClient)
        result = CloudAnalysis(
            novel_id="raw-novel",
            foreshadow_rate=0.1,
            arc_scores={"角色0": 8.5},
            narrative_type="三幕",
            topic_labels=["成长"],
            diagnosis="ok",
            narrative_arc_type="白手起家",
            protagonist="角色0",
            main_characters=["角色0"],
            core_cast=["角色0", "角色1"],
        )

        finalized = client._finalize_result(result, "fixed-novel")

        assert finalized.novel_id == "fixed-novel"
        assert finalized.protagonist == "角色0"
        assert finalized.main_characters == ["角色0"]
        assert finalized.core_cast == ["角色0", "角色1"]

    def test_build_messages_uses_alias_merges(self) -> None:
        client = object.__new__(DiagnosisClient)

        messages = client._build_messages(
            {
                "novel_id": self.novel_id,
                "known_characters": ["伯安"],
                "alias_merges": {"角色0": "伯安"},
            }
        )

        assert "alias_merges" in messages[0]["content"]
        assert "known_characters" in messages[0]["content"]
        assert '"角色0": "伯安"' in messages[0]["content"]
