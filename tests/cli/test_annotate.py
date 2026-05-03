"""
CLI annotate 模块测试

创建时间: 2025-03-11
任务: 测试标注流程

修改时间: 2026-03-15
任务: storage-layer-decoupling
修改内容: 使用 SessionFactory 替代 connect_db/create_tables，消除 DeprecationWarning

修改时间: 2026-03-15
任务: postgresql-migration
修改内容: 使用 SQLAlchemy text() 替换 ? 占位符，移除 sqlite3 导入

修改时间: 2026-03-15
任务: postgresql-migration-cleanup
修改内容: 改用 PostgreSQL db_session fixture，移除 SessionFactory 依赖

修改时间: 2026-03-29
任务: refactor-phase1-identity-extraction
修改内容: 移除 relations 字段相关测试
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import Chunk
from src.models.annotation import AnnotationClient
from src.models.disambiguation import DisambiguationClient
from src.models.local.annotation import MultiPhaseAnnotationResult
from src.models.local.disambiguation import ExtendedDisambigResult
from src.models.local.schema import CharacterSnapshot, ChunkAnnotation, DialogueSnapshot
from src.storage.models import Novel
from src.storage.repositories import ChunkRepository, RunRepository
from src.workflows.annotate import run_annotate


def _insert_test_novel(db_session, novel_id: str) -> None:
    """
    创建测试用 Novel 记录，避免 create_run 时 ForeignKeyViolation。

    创建时间: 2026-04-23
    任务: 修复 pytest ForeignKeyViolation
    """
    db_session.add(
        Novel(
            novel_id=novel_id,
            filename=f"{novel_id}.txt",
            file_path=f"data/uploads/{novel_id}.txt",
            file_size=128,
        )
    )
    db_session.commit()


def create_mock_annotation() -> MultiPhaseAnnotationResult:
    """
    创建模拟的 MultiPhaseAnnotationResult

    修改时间: 2026-03-18
    任务: code-quality-refactor - 修复测试以适应 MultiPhaseAnnotationResult 返回类型

    修改时间: 2026-03-29
    任务: refactor-phase1-identity-extraction
    修改内容: 移除 relations 字段
    """
    return MultiPhaseAnnotationResult(
        annotation=ChunkAnnotation(
            emotional_valence="neutral",
            event_type="铺垫",
            pivot_moment=False,
            cliffhanger=False,
            has_foreshadowing=False,
            foreshadowing_type=None,
            foreshadowing_desc="",
            characters=[
                CharacterSnapshot(
                    name="张三",
                    role_function="主体",
                    action="测试行为",
                    action_type="其他",
                    emotion_score="neutral",
                )
            ],
            dialogues=[
                DialogueSnapshot(
                    index=1,
                    content="测试对话内容",
                    is_dialogue=True,
                    speaker=["张三"],
                    tone="neutral",
                    is_inner_monologue=False,
                    evidence="测试依据",
                    identity_clue=None,
                )
            ],
        ),
        foreshadowing=None,
        dialogue_lengths={"张三": 5},
        dialogue_speakers={0: ["张三"]},
        dialogues=[(1, "测试对话内容")],
    )


class TestAnnotate:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, self.novel_id)

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def _create_chunks(self, chunk_count: int) -> None:
        chunk_repo = ChunkRepository(self.db_session)
        chunks = [Chunk(index=i, start=0, end=10, text=f"测试文本{i}") for i in range(chunk_count)]
        chunk_repo.insert_chunks(self.run_id, chunks)

    @pytest.mark.asyncio()
    @patch("src.workflows.annotate_helpers.context._init_evidence_service")
    @patch("src.workflows.annotate_helpers.client_init.DisambiguationClient")
    @patch("src.workflows.annotate_helpers.client_init.AnnotationClient")
    async def test_annotate_basic(
        self,
        mock_annotation_class: MagicMock,
        mock_disambiguation_class: MagicMock,
        mock_evidence_service: MagicMock,
    ) -> None:
        mock_evidence_service.return_value = None

        mock_annotation_client = MagicMock(spec=AnnotationClient)
        mock_annotation_client.annotate_chunk.return_value = create_mock_annotation()
        mock_annotation_client._config = MagicMock(model="test-model", thinking_enabled=False)
        mock_disambiguation_client = MagicMock(spec=DisambiguationClient)
        mock_disambiguation_client.disambiguate_characters.return_value = ExtendedDisambigResult(
            canonical_decisions={}, entity_types={}, entity_relations=[]
        )
        mock_annotation_class.return_value = mock_annotation_client
        mock_disambiguation_class.return_value = mock_disambiguation_client

        self._create_chunks(3)

        success, errors, total = await run_annotate(
            run_id=self.run_id,
            session=self.db_session,
            resume=False,
            novel_id=self.novel_id,
        )
        assert success == 3
        assert errors == 0
        assert total == 3

        annotation_count = self.db_session.execute(
            text("SELECT COUNT(*) FROM chunk_annotation WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        character_count = self.db_session.execute(
            text("SELECT COUNT(*) FROM chunk_characters WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        dialogue_count = self.db_session.execute(
            text("SELECT COUNT(*) FROM chunk_dialogues WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        assert annotation_count == 3
        assert character_count == 3
        assert dialogue_count == 3

    @pytest.mark.asyncio()
    @patch("src.workflows.annotate_helpers.context._init_evidence_service")
    @patch("src.workflows.annotate_helpers.client_init.DisambiguationClient")
    @patch("src.workflows.annotate_helpers.client_init.AnnotationClient")
    async def test_annotate_resume(
        self, mock_annotation_class: MagicMock, mock_disambiguation_class: MagicMock, mock_evidence_service: MagicMock
    ) -> None:
        mock_evidence_service.return_value = None

        mock_annotation_client = MagicMock(spec=AnnotationClient)
        mock_annotation_client.annotate_chunk.return_value = create_mock_annotation()
        mock_annotation_client._config = MagicMock(model="test-model", thinking_enabled=False)
        mock_disambiguation_client = MagicMock(spec=DisambiguationClient)
        mock_disambiguation_client.disambiguate_characters.return_value = ExtendedDisambigResult(
            canonical_decisions={}, entity_types={}, entity_relations=[]
        )
        mock_annotation_class.return_value = mock_annotation_client
        mock_disambiguation_class.return_value = mock_disambiguation_client

        self._create_chunks(5)

        success1, errors1, total1 = await run_annotate(
            run_id=self.run_id,
            session=self.db_session,
            resume=False,
            novel_id=self.novel_id,
        )
        assert success1 == 5

        self.db_session.execute(
            text("DELETE FROM chunk_annotation WHERE chunk_id = 2 AND run_id = :run_id"),
            {"run_id": self.run_id},
        )
        self.db_session.execute(
            text("DELETE FROM chunk_characters WHERE chunk_id = 2 AND run_id = :run_id"),
            {"run_id": self.run_id},
        )
        self.db_session.execute(
            text("DELETE FROM chunk_dialogues WHERE chunk_id = 2 AND run_id = :run_id"),
            {"run_id": self.run_id},
        )
        self.db_session.commit()

        success2, errors2, total2 = await run_annotate(
            run_id=self.run_id,
            session=self.db_session,
            resume=True,
            novel_id=self.novel_id,
        )
        assert success2 == 1
        assert errors2 == 0

        annotation_count = self.db_session.execute(
            text("SELECT COUNT(*) FROM chunk_annotation WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        assert annotation_count == 5

    @pytest.mark.asyncio()
    @patch("src.workflows.annotate_helpers.context._init_evidence_service")
    @patch("src.workflows.annotate_helpers.client_init.DisambiguationClient")
    @patch("src.workflows.annotate_helpers.client_init.AnnotationClient")
    async def test_annotate_disambiguation(
        self, mock_annotation_class: MagicMock, mock_disambiguation_class: MagicMock, mock_evidence_service: MagicMock
    ) -> None:
        mock_evidence_service.return_value = None

        mock_annotation_client = MagicMock(spec=AnnotationClient)
        mock_annotation_client.annotate_chunk.return_value = create_mock_annotation()
        mock_annotation_client._config = MagicMock(model="test-model", thinking_enabled=False)
        mock_disambiguation_client = MagicMock(spec=DisambiguationClient)
        mock_disambiguation_client.disambiguate_characters.return_value = ExtendedDisambigResult(
            canonical_decisions={"张三三": "张三"}, entity_types={}, entity_relations=[]
        )
        mock_annotation_class.return_value = mock_annotation_client
        mock_disambiguation_class.return_value = mock_disambiguation_client

        self._create_chunks(2)

        success, errors, total = await run_annotate(
            run_id=self.run_id,
            session=self.db_session,
            resume=False,
            novel_id=self.novel_id,
        )
        assert success == 2

        self.db_session.execute(
            text(
                "INSERT INTO chunk_characters (chunk_id, name, role_function, action, action_type, emotion_score, run_id) VALUES (1, '张三三', '其他', 'test', '其他', 'neutral', :run_id)"
            ),
            {"run_id": self.run_id},
        )
        self.db_session.commit()

        success2, errors2, total2 = await run_annotate(
            run_id=self.run_id,
            session=self.db_session,
            resume=True,
            novel_id=self.novel_id,
        )

        names = [
            row[0]
            for row in self.db_session.execute(
                text("SELECT DISTINCT name FROM chunk_characters WHERE run_id = :run_id"),
                {"run_id": self.run_id},
            )
        ]
        assert "张三" in names
