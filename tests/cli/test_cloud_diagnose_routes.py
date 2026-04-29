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

修改时间: 2026-04-08
修改者: GLM-5
任务: summary-full-chain-refactor
修改内容: 移除 first_chapter_summary/last_chapter_summary 测试，新增 summaries 测试
"""

import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
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
from src.storage.models import ChunkRelation
from src.storage.repositories import (
    AnnotationRepository,
    ChunkRepository,
    ChunkStyleData,
    DiagnosisRepository,
    GraphRepository,
    RunRepository,
    StatsRepository,
)
from src.workflows.diagnose import run_diagnose


def _insert_test_novel(session, novel_id: str) -> None:
    """
    为云端诊断测试补小说主表记录。

    创建时间: 2026-04-22
    创建者: Codex
    任务: fix-analysis-related-foreign-keys
    说明: diagnosis 测试直接造 run 时，必须先满足 analysis_runs 的 novel 外键。
    """
    session.execute(
        text(
            """
            INSERT INTO novels (novel_id, title, filename, file_path)
            VALUES (:novel_id, :title, :filename, :file_path)
            ON CONFLICT (novel_id) DO NOTHING
            """
        ),
        {
            "novel_id": novel_id,
            "title": novel_id,
            "filename": f"{novel_id}.txt",
            "file_path": f"data/uploads/{novel_id}.txt",
        },
    )
    session.commit()


class TestCloudDiagnose:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, self.novel_id)

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def _create_full_data(self, chunk_count: int = 5) -> None:
        chunk_repo = ChunkRepository(self.db_session)
        chunks = [
            Chunk(index=i, start=0, end=100, text=f"这是第{i}个测试文本，包含一些内容。") for i in range(chunk_count)
        ]
        chunk_repo.insert_chunks(self.run_id, chunks)
        # 中文注释：diagnosis 现在会校验 topic_labels 数量必须和本次真正发送给 LLM 的 topic_words 数一致；
        # 测试基线需要显式造出至少一个主题，避免 payload.topic_words 为空时再用“单主题标签”样例误报。
        chunk_repo.insert_chunk_topics(self.run_id, [(i, 0, 1.0) for i in range(chunk_count)])

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
                    "INSERT INTO chunk_curves ("
                    "chunk_id, pos_density, neg_density, net_density, smoothed_density, "
                    "tension_proxy, tension_composite, run_id"
                    ") VALUES (:chunk_id, :pos, :neg, :net, :smoothed, :proxy, :composite, :run_id)"
                ),
                {
                    "chunk_id": i,
                    "pos": 0.1,
                    "neg": 0.05,
                    "net": 0.05 + i * 0.01,
                    "smoothed": 0.05,
                    "proxy": 0.5,
                    "composite": 0.5,
                    "run_id": self.run_id,
                },
            )

        ann_repo = AnnotationRepository(self.db_session)
        for i in range(chunk_count):
            annotation = ChunkAnnotation(
                emotional_valence="mild_positive" if i % 2 == 0 else "mild_negative",
                event_type="高潮" if i in [1, 2] else ("转折" if i == 3 else "铺垫"),
                pivot_moment=(i in [1, 2]),
                cliffhanger=(i == chunk_count - 1),
                has_foreshadowing=(i == 0),
                foreshadowing_type="场景" if i == 0 else None,
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
                INSERT INTO disambig_checkpoint (run_id, state_json, updated_at)
                VALUES (:run_id, :state_json, :updated_at)
                """
            ),
            {
                "run_id": self.run_id,
                "state_json": json.dumps(state_payload, ensure_ascii=False),
                "updated_at": 1.0,
            },
        )
        self.db_session.commit()

        payload = build_diagnosis_payload(self.db_session, self.novel_id, self.run_id)

        assert payload["novel_id"] == self.novel_id
        assert "pivot_blocks" in payload
        assert "pivot_moments" in payload
        assert "high_tension_paragraphs" in payload
        assert "character_relations" in payload
        assert "foreshadowing_threads" in payload
        assert "foreshadow_expectation" in payload
        assert "genre_labels" in payload
        assert "summaries" in payload
        assert "known_characters" in payload
        assert "alias_merges" in payload
        assert "graph_summary" in payload
        assert "graph_quality_report" in payload

        assert len(payload["pivot_blocks"]) > 0
        assert len(payload["pivot_moments"]) > 0
        assert len(payload["foreshadowing_threads"]) >= 0
        assert payload["genre_labels"]
        assert payload["known_characters"] == ["伯安"]
        assert payload["alias_merges"] == {"角色0": "伯安"}
        assert set(payload["graph_summary"].keys()) == {"node_count", "edge_count", "density"}
        assert "conflict_count" in payload["graph_quality_report"]
        assert "low_confidence_count" in payload["graph_quality_report"]

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

    def test_build_diagnosis_payload_excludes_final_disambiguation_relation_changes(self) -> None:
        """
        创建时间: 2026-04-29
        任务: graph-diagnosis-mainline-blockers
        说明: diagnosis payload 的 character_relations 必须复用 graph history 过滤，
              final_disambiguation 的 synthetic relation 不能再从 fetch_relation_changes 漏回云端诊断。
        """
        self._create_full_data(3)

        graph_repo = GraphRepository(self.db_session)
        hero = graph_repo.upsert_entity(run_id=self.run_id, canonical_name="顾霜", first_seen_chunk=1, last_seen_chunk=1)
        ally = graph_repo.upsert_entity(run_id=self.run_id, canonical_name="贺家", first_seen_chunk=1, last_seen_chunk=1)
        synthetic_relation = ChunkRelation(
            chunk_id=1,
            run_id=self.run_id,
            from_char="阿顾",
            to_char="贺家",
            resolved_from_global_name="顾霜",
            resolved_to_global_name="贺家",
            type="belongs_to",
            change="新建",
            evidence="阿顾属于贺家",
            confidence=0.91,
            source_model="final_disambiguation",
            projection_status="projected",
        )
        self.db_session.add(synthetic_relation)
        self.db_session.flush()

        graph_repo.insert_relation_event(
            run_id=self.run_id,
            from_entity_id=hero.entity_id,
            to_entity_id=ally.entity_id,
            relation_type="belongs_to",
            change_type="新建",
            chunk_id=1,
            evidence="阿顾属于贺家",
            confidence=0.91,
            source_relation_row_id=synthetic_relation.id,
            directionality="directed",
        )
        graph_repo.refresh_current_relation(self.run_id, hero.entity_id, ally.entity_id)
        graph_repo.refresh_entity_participants(self.run_id, [hero.entity_id, ally.entity_id])
        self.db_session.commit()

        diag_repo = DiagnosisRepository(self.db_session)
        payload = build_diagnosis_payload(self.db_session, self.novel_id, self.run_id)

        assert diag_repo.fetch_relation_changes(self.run_id) == []
        assert payload["character_relations"] == []

    def test_fetch_foreshadowing_chunks(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        chunks = diag_repo.fetch_foreshadowing_chunks(self.run_id)
        assert len(chunks) > 0

    def test_fetch_pivot_moments(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisRepository(self.db_session)
        moments = diag_repo.fetch_pivot_moments(self.run_id)
        assert len(moments) > 0

    @pytest.mark.asyncio()
    async def test_run_diagnose_with_cloud(self) -> None:
        self._create_full_data(5)

        analysis = await run_diagnose(
            run_id=self.run_id,
            session=self.db_session,
            client=FakeClient(),
        )
        assert analysis is not None
        assert analysis.genre_labels == ["通用"]
        assert analysis.style_labels == ["严肃"]
        assert analysis.foreshadow_expectation == 0.1

        rows = self.db_session.execute(
            text("SELECT COUNT(*) FROM cloud_analysis WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        assert rows > 0

    @pytest.mark.asyncio()
    async def test_run_diagnose_persists_result(self) -> None:
        self._create_full_data(3)

        await run_diagnose(
            run_id=self.run_id,
            session=self.db_session,
            client=FakeClient(),
        )
        rows = self.db_session.execute(
            text(
                "SELECT novel_id, genre_labels, style_labels, foreshadow_expectation, narrative_arc_type, "
                "focus_structure, focus_characters, main_characters, core_cast "
                "FROM cloud_analysis WHERE run_id = :run_id"
            ),
            {"run_id": self.run_id},
        ).fetchall()
        assert len(rows) > 0
        assert rows[0][0] == self.novel_id
        assert rows[0][1] == '["通用"]'
        assert rows[0][2] == '["严肃"]'
        assert rows[0][4] == "白手起家"
        assert rows[0][5] == "dual"
        assert "角色0" in rows[0][6]
        assert "角色0" in rows[0][7]
        assert "角色1" in rows[0][8]

        token_rows = self.db_session.execute(
            text("SELECT novel_id FROM token_usage WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalars().all()
        assert all(novel_id == self.novel_id for novel_id in token_rows)

        stats_repo = StatsRepository(self.db_session)
        fetched = stats_repo.fetch_cloud_analysis(self.novel_id, self.run_id)
        assert fetched is not None
        assert fetched["focus_structure"] == "dual"
        assert fetched["focus_characters"] is not None
        assert fetched["main_characters"] is not None
        assert fetched["core_cast"] is not None

    @pytest.mark.asyncio()
    async def test_run_diagnose_persists_model_interaction(self) -> None:
        """
        修改时间: 2026-04-25
        修改者: Codex
        任务: remove-diagnosis-cache-and-fix-interaction-persistence
        修改内容: 回归验证 diagnosis 阶段的 prompt/response/thinking 会写入 model_interactions。
        """
        self._create_full_data(3)

        content = json.dumps(
            {
                "novel_id": self.novel_id,
                "foreshadow_expectation": 0.2,
                "arc_scores": {"角色0": 9.1, "角色1": 7.8},
                "genre_labels": ["通用"],
                "style_labels": ["严肃"],
                "topic_labels": ["成长"],
                "diagnosis": "诊断完成",
                "narrative_arc_type": "白手起家",
                "focus_structure": "single",
                "focus_characters": ["角色0"],
                "main_characters": ["角色0"],
                "core_cast": ["角色0", "角色1"],
            },
            ensure_ascii=False,
        )
        raw_response = MagicMock()
        raw_response.choices = [MagicMock(message=MagicMock(content=content))]
        structured_result = SimpleNamespace(
            parsed=CloudAnalysis.model_validate_json(content),
            raw_response=raw_response,
            response_text=content,
            thinking_content="诊断思考内容",
            reasoning_tokens=17,
        )
        diagnose_client = DiagnosisClient(
            client=MagicMock(),
            analysis_logger=None,
            session=self.db_session,
        )

        with patch(
            "src.models.diagnosis.call_structured_output",
            new=AsyncMock(return_value=structured_result),
        ):
            await run_diagnose(
                run_id=self.run_id,
                session=self.db_session,
                client=diagnose_client,
            )

        row = self.db_session.execute(
            text(
                """
                SELECT interaction_type, phase, response, thinking, reasoning_tokens
                FROM model_interactions
                WHERE run_id = :run_id AND interaction_type = 'diagnose'
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"run_id": self.run_id},
        ).mappings().one()
        assert row["interaction_type"] == "diagnose"
        assert row["phase"] == "diagnose"
        assert row["reasoning_tokens"] == 17
        assert "诊断完成" in row["response"]
        assert row["thinking"] == "诊断思考内容"

    def test_finalize_result_preserves_character_fields(self) -> None:
        client = object.__new__(DiagnosisClient)
        result = CloudAnalysis(
            novel_id="raw-novel",
            foreshadow_expectation=0.1,
            arc_scores={"角色0": 8.5, "角色1": 7.1},
            genre_labels=["科幻"],
            style_labels=["严肃"],
            topic_labels=["成长"],
            diagnosis="ok",
            narrative_arc_type="白手起家",
            focus_structure="single",
            focus_characters=["角色0"],
            main_characters=["角色0"],
            core_cast=["角色0", "角色1"],
        )

        finalized = client._finalize_result(result, "fixed-novel", payload={})

        assert finalized.novel_id == "fixed-novel"
        assert finalized.genre_labels == ["科幻"]
        assert finalized.focus_structure == "single"
        assert finalized.focus_characters == ["角色0"]
        assert finalized.main_characters == ["角色0"]
        assert finalized.core_cast == ["角色0", "角色1"]

    def test_finalize_result_overrides_genre_labels_from_payload(self) -> None:
        """
        创建时间: 2026-04-29
        创建者: Codex
        任务: split-diagnosis-genre-style-labels
        说明: 稳定题材数组必须以 payload 为真相源，不能继续信任模型自由发挥的 genre 输出。
        """

        client = object.__new__(DiagnosisClient)
        result = CloudAnalysis(
            novel_id="raw-novel",
            foreshadow_expectation=0.1,
            arc_scores={"角色0": 8.5, "角色1": 7.1},
            genre_labels=["通用"],
            style_labels=["严肃"],
            topic_labels=["成长"],
            diagnosis="ok",
            narrative_arc_type="白手起家",
            focus_structure="single",
            focus_characters=["角色0"],
            main_characters=["角色0"],
            core_cast=["角色0", "角色1"],
        )

        finalized = client._finalize_result(
            result,
            "fixed-novel",
            payload={"genre_labels": ["科幻"]},
        )

        assert finalized.genre_labels == ["科幻"]

    def test_finalize_result_overrides_expectation_from_payload(self) -> None:
        """
        创建时间: 2026-04-29
        任务: foreshadow-expectation-v2
        新建原因: diagnosis LLM 不再拥有 foreshadow_expectation，最终结果必须始终以 payload 的 ledger 计算值为准。
        """

        client = object.__new__(DiagnosisClient)
        result = CloudAnalysis(
            novel_id="raw-novel",
            foreshadow_expectation=0.27,
            arc_scores={"角色0": 8.5, "角色1": 7.1},
            genre_labels=["通用"],
            style_labels=["严肃"],
            topic_labels=["成长"],
            diagnosis="ok",
            narrative_arc_type="白手起家",
            focus_structure="single",
            focus_characters=["角色0"],
            main_characters=["角色0"],
            core_cast=["角色0", "角色1"],
        )

        finalized = client._finalize_result(
            result,
            "fixed-novel",
            payload={"foreshadow_expectation": 0.42},
        )

        assert finalized.foreshadow_expectation == 0.42

    def test_finalize_result_rejects_partial_topic_labels_against_payload_topic_words(self) -> None:
        """
        创建时间: 2026-04-27
        创建者: Codex
        任务: fix-diagnosis-topic-label-count-contract
        说明: diagnosis 结果里的 topic_labels 会被主题页按位置消费；
        如果本次实际发给 LLM 的 topic_words 有多个，而返回标签数不足，就必须在落库前直接拒绝。
        """

        client = object.__new__(DiagnosisClient)
        result = CloudAnalysis(
            novel_id="raw-novel",
            foreshadow_expectation=0.1,
            arc_scores={"角色0": 8.5, "角色1": 7.1},
            genre_labels=["通用"],
            style_labels=["严肃"],
            topic_labels=["成长"],
            diagnosis="ok",
            narrative_arc_type="白手起家",
            focus_structure="single",
            focus_characters=["角色0"],
            main_characters=["角色0"],
            core_cast=["角色0", "角色1"],
        )

        with pytest.raises(ValueError, match="topic_labels count must match payload.topic_words count"):
            client._finalize_result(
                result,
                "fixed-novel",
                payload={
                    "topic_words": [
                        ["成长", "修炼", "历练"],
                        ["命运", "抉择", "因果"],
                    ]
                },
            )

    def test_finalize_result_accepts_topic_labels_when_count_matches_payload_topic_words(self) -> None:
        """
        创建时间: 2026-04-27
        创建者: Codex
        任务: fix-diagnosis-topic-label-count-contract
        说明: 多主题 payload 只要返回标签数量和本次发送给 LLM 的 topic_words 数一致，
        就应允许正常落库，不把合法 diagnosis 误判为坏结果。
        """

        client = object.__new__(DiagnosisClient)
        result = CloudAnalysis(
            novel_id="raw-novel",
            foreshadow_expectation=0.1,
            arc_scores={"角色0": 8.5, "角色1": 7.1},
            genre_labels=["通用"],
            style_labels=["严肃"],
            topic_labels=["成长", "命运"],
            diagnosis="ok",
            narrative_arc_type="白手起家",
            focus_structure="single",
            focus_characters=["角色0"],
            main_characters=["角色0"],
            core_cast=["角色0", "角色1"],
        )

        finalized = client._finalize_result(
            result,
            "fixed-novel",
            payload={
                "topic_words": [
                    ["成长", "修炼", "历练"],
                    ["命运", "抉择", "因果"],
                ]
            },
        )

        assert finalized.topic_labels == ["成长", "命运"]

    def test_cloud_analysis_rejects_formal_diagnosis_missing_focus_contract(self) -> None:
        """
        创建时间: 2026-04-27
        创建者: Codex
        任务: protagonist-focus-contract-review-fixes
        说明: 当前分支已经硬切焦点合同；只要是正式 diagnosis 结果，
        就不能再依赖默认值落出缺 `focus_structure` / `focus_characters` 的半成品对象。
        """

        with pytest.raises(ValidationError):
            CloudAnalysis(
                novel_id="raw-novel",
                foreshadow_expectation=0.1,
                arc_scores={"角色0": 8.5, "角色1": 7.1},
                genre_labels=["通用"],
                style_labels=["严肃"],
                topic_labels=["成长"],
                diagnosis="ok",
                narrative_arc_type="白手起家",
                main_characters=["角色0"],
                core_cast=["角色0", "角色1"],
            )

    def test_cloud_analysis_rejects_formal_diagnosis_missing_main_and_core_cast(self) -> None:
        """
        创建时间: 2026-04-27
        创建者: Codex
        任务: protagonist-focus-contract-review-fixes-round2
        说明: 新焦点合同不允许主要人物/核心角色静默缺失；
        正式 diagnosis 缺这两个字段时，模型层必须直接拒绝。
        """

        with pytest.raises(ValidationError):
            CloudAnalysis(
                novel_id="raw-novel",
                foreshadow_expectation=0.1,
                arc_scores={"角色0": 8.5, "角色1": 7.1},
                genre_labels=["通用"],
                style_labels=["严肃"],
                topic_labels=["成长"],
                diagnosis="ok",
                narrative_arc_type="白手起家",
                focus_structure="single",
                focus_characters=["角色0"],
            )

    def test_cloud_analysis_rejects_formal_diagnosis_missing_topic_labels(self) -> None:
        """
        创建时间: 2026-04-27
        创建者: Codex
        任务: protagonist-focus-contract-review-fixes-round5
        说明: 正式 diagnosis 合同同样要求完整主题命名；
        如果 topic_labels 缺失，模型层必须直接拒绝，不能落成“焦点合同完整但主题命名为空”的半成品。
        """

        with pytest.raises(ValidationError):
            CloudAnalysis(
                novel_id="raw-novel",
                foreshadow_expectation=0.1,
                arc_scores={"角色0": 8.5, "角色1": 7.1},
                genre_labels=["通用"],
                style_labels=["严肃"],
                diagnosis="ok",
                narrative_arc_type="白手起家",
                focus_structure="single",
                focus_characters=["角色0"],
                main_characters=["角色0"],
                core_cast=["角色0", "角色1"],
            )

    def test_cloud_analysis_rejects_main_characters_over_limit(self) -> None:
        with pytest.raises(ValidationError):
            CloudAnalysis(
                novel_id="raw-novel",
                foreshadow_expectation=0.1,
                arc_scores={f"角色{i}": 7.0 + i for i in range(6)},
                genre_labels=["通用"],
                style_labels=["严肃"],
                topic_labels=["成长"],
                diagnosis="ok",
                narrative_arc_type="白手起家",
                focus_structure="single",
                focus_characters=["角色0"],
                main_characters=[f"角色{i}" for i in range(6)],
                core_cast=[f"角色{i}" for i in range(6)],
            )

    def test_cloud_analysis_rejects_core_cast_over_limit(self) -> None:
        with pytest.raises(ValidationError):
            CloudAnalysis(
                novel_id="raw-novel",
                foreshadow_expectation=0.1,
                arc_scores={f"角色{i}": 7.0 + i for i in range(11)},
                genre_labels=["通用"],
                style_labels=["严肃"],
                topic_labels=["成长"],
                diagnosis="ok",
                narrative_arc_type="白手起家",
                focus_structure="single",
                focus_characters=["角色0"],
                main_characters=["角色0"],
                core_cast=[f"角色{i}" for i in range(11)],
            )

    def test_finalize_result_resets_expectation_to_none_when_payload_has_no_ledger_value(self) -> None:
        """
        创建时间: 2026-04-26
        创建者: Codex
        任务: fix-diagnosis-review-findings
        说明: setup ledger 合法为空时，payload 会显式给出 `foreshadow_expectation=None`；
        此时必须覆写掉 LLM 自行猜测的数值，继续保持单一真相源。
        """

        client = object.__new__(DiagnosisClient)
        result = CloudAnalysis(
            novel_id="raw-novel",
            foreshadow_expectation=0.27,
            arc_scores={"角色0": 8.5, "角色1": 7.1},
            genre_labels=["通用"],
            style_labels=["严肃"],
            topic_labels=["成长"],
            diagnosis="ok",
            narrative_arc_type="白手起家",
            focus_structure="single",
            focus_characters=["角色0"],
            main_characters=["角色0"],
            core_cast=["角色0", "角色1"],
        )

        finalized = client._finalize_result(result, "fixed-novel", payload={"foreshadow_expectation": None})

        assert finalized.novel_id == "fixed-novel"
        assert finalized.foreshadow_expectation is None

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
