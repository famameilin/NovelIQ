"""
CLI annotate 模块测试（LangGraph 标注 Agent）

说明: run_annotate 已 agent 化，测试通过 patch run_annotation_agent 注入假合并标注结果
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.agents.annotation import AnnotationChunkResult, IdentityMemory
from src.chunking.chunker import Chunk
from src.models.local.schema import CharacterSnapshot, ChunkAnnotation
from src.storage.models import Novel
from src.storage.repositories import ChunkRepository, RunRepository
from src.workflows.annotate import run_annotate


def _insert_test_novel(db_session, novel_id: str) -> None:
    """
    创建测试用 Novel 记录，避免 create_run 时 ForeignKeyViolation
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


def _make_agent_result() -> AnnotationChunkResult:
    """构造假标注 agent 输出（合并结果）"""
    return AnnotationChunkResult(
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
            dialogues=[],
        ),
        foreshadowing=None,
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

    def _patch_agent(self, mock_agent: MagicMock) -> None:
        mock_agent.side_effect = [
            (_make_agent_result(), IdentityMemory()) for _ in range(100)
        ]

    @pytest.mark.asyncio()
    @patch("src.workflows.annotate_helpers._extract_and_save_global_context", new=AsyncMock(return_value=None))
    @patch("src.workflows.annotate_helpers._init_evidence_service", return_value=None)
    async def test_annotate_basic(
        self,
        mock_evidence_service: MagicMock,
    ) -> None:
        with patch("src.agents.annotation.run_annotation_agent", new=AsyncMock()) as mock_agent:
            self._patch_agent(mock_agent)

            self._create_chunks(3)

            success, errors, total = await run_annotate(
                run_id=self.run_id,
                session=self.db_session,
                resume=False,
                novel_id=self.novel_id,
                use_rag=False,
            )
        assert success == 3
        assert errors == 0
        assert total == 3
        assert mock_agent.await_count == 3

        annotation_count = self.db_session.execute(
            text("SELECT COUNT(*) FROM chunk_annotation WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        character_count = self.db_session.execute(
            text("SELECT COUNT(*) FROM chunk_characters WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        assert annotation_count == 3
        assert character_count == 3

    @pytest.mark.asyncio()
    @patch("src.workflows.annotate_helpers._extract_and_save_global_context", new=AsyncMock(return_value=None))
    @patch("src.workflows.annotate_helpers._init_evidence_service", return_value=None)
    async def test_annotate_resume(
        self,
        mock_evidence_service: MagicMock,
    ) -> None:
        with patch("src.agents.annotation.run_annotation_agent", new=AsyncMock()) as mock_agent:
            self._patch_agent(mock_agent)

            self._create_chunks(5)

            success1, errors1, total1 = await run_annotate(
                run_id=self.run_id,
                session=self.db_session,
                resume=False,
                novel_id=self.novel_id,
                use_rag=False,
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
        self.db_session.commit()

        with patch("src.agents.annotation.run_annotation_agent", new=AsyncMock()) as mock_agent:
            mock_agent.reset_mock()
            self._patch_agent(mock_agent)

            success2, errors2, total2 = await run_annotate(
                run_id=self.run_id,
                session=self.db_session,
                resume=True,
                novel_id=self.novel_id,
                use_rag=False,
            )
        assert success2 == 1
        assert errors2 == 0
        assert mock_agent.await_count == 1

        annotation_count = self.db_session.execute(
            text("SELECT COUNT(*) FROM chunk_annotation WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        assert annotation_count == 5
