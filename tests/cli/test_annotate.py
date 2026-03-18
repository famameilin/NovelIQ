"""
CLI annotate 模块测试

创建时间: 2025-03-11
创建者: TraeAI
任务: 测试标注流程

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
"""
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.storage.repositories import ChunkRepository, RunRepository
from src.workflows.annotate import run_annotate
from src.chunking.chunker import Chunk
from src.models.local.unified_client import UnifiedModelClient
from src.models.local.schema import ChunkAnnotation, CharacterSnapshot, RelationChangeSnapshot, DialogueSnapshot
from src.models.local.annotation import TwoPhaseAnnotationResult


def create_mock_annotation() -> TwoPhaseAnnotationResult:
    """
    创建模拟的 TwoPhaseAnnotationResult

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: code-quality-refactor - 修复测试以适应 TwoPhaseAnnotationResult 返回类型
    """
    return TwoPhaseAnnotationResult(
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
            relations=[
                RelationChangeSnapshot(
                    from_name="张三",
                    to_name="李四",
                    type="盟友",
                    change="新建",
                )
            ],
            dialogues=[
                DialogueSnapshot(speaker="张三"),
            ],
        ),
        foreshadowing=None,
    )


class TestAnnotate:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = f"test_novel_{uuid.uuid4().hex[:8]}"

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def _create_chunks(self, chunk_count: int) -> None:
        chunk_repo = ChunkRepository(self.db_session)
        chunks = [Chunk(index=i, start=0, end=10, text=f"张三在测试文本{i}中行动") for i in range(chunk_count)]
        chunk_repo.insert_chunks(self.run_id, chunks)

    @patch("src.workflows.annotate_helpers.client_init.UnifiedModelClient")
    def test_annotate_basic(self, mock_client_class: MagicMock) -> None:
        mock_client = MagicMock(spec=UnifiedModelClient)
        mock_client.annotate_chunk.return_value = create_mock_annotation()
        mock_client.disambiguate_characters.return_value = {}
        mock_client_class.return_value = mock_client

        self._create_chunks(3)

        success, errors, total = run_annotate(
            run_id=self.run_id,
            session=self.db_session,
            resume=False,
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
        relation_count = self.db_session.execute(
            text("SELECT COUNT(*) FROM chunk_relations WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        dialogue_count = self.db_session.execute(
            text("SELECT COUNT(*) FROM chunk_dialogues WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        assert annotation_count == 3
        assert character_count == 3
        assert relation_count == 3
        assert dialogue_count == 3

    @patch("src.workflows.annotate_helpers.client_init.UnifiedModelClient")
    def test_annotate_resume(self, mock_client_class: MagicMock) -> None:
        mock_client = MagicMock(spec=UnifiedModelClient)
        mock_client.annotate_chunk.return_value = create_mock_annotation()
        mock_client.disambiguate_characters.return_value = {}
        mock_client_class.return_value = mock_client

        self._create_chunks(5)

        success1, errors1, total1 = run_annotate(
            run_id=self.run_id,
            session=self.db_session,
            resume=False,
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
            text("DELETE FROM chunk_relations WHERE chunk_id = 2 AND run_id = :run_id"),
            {"run_id": self.run_id},
        )
        self.db_session.execute(
            text("DELETE FROM chunk_dialogues WHERE chunk_id = 2 AND run_id = :run_id"),
            {"run_id": self.run_id},
        )
        self.db_session.commit()

        success2, errors2, total2 = run_annotate(
            run_id=self.run_id,
            session=self.db_session,
            resume=True,
        )
        assert success2 == 1
        assert errors2 == 0

        annotation_count = self.db_session.execute(
            text("SELECT COUNT(*) FROM chunk_annotation WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        assert annotation_count == 5

    @patch("src.workflows.annotate_helpers.client_init.UnifiedModelClient")
    def test_annotate_disambiguation(self, mock_client_class: MagicMock) -> None:
        mock_client = MagicMock(spec=UnifiedModelClient)
        mock_client.annotate_chunk.return_value = create_mock_annotation()
        mock_client.disambiguate_characters.return_value = {"张三丰": "张三"}
        mock_client_class.return_value = mock_client

        self._create_chunks(2)

        success, errors, total = run_annotate(
            run_id=self.run_id,
            session=self.db_session,
            resume=False,
        )
        assert success == 2

        self.db_session.execute(
            text("INSERT INTO chunk_characters (chunk_id, name, role_function, action, action_type, emotion_score, run_id) VALUES (1, '张三丰', '其他', 'test', '其他', 'neutral', :run_id)"),
            {"run_id": self.run_id},
        )
        self.db_session.commit()

        success2, errors2, total2 = run_annotate(
            run_id=self.run_id,
            session=self.db_session,
            resume=True,
        )

        names = [
            row[0]
            for row in self.db_session.execute(
                text("SELECT DISTINCT name FROM chunk_characters WHERE run_id = :run_id"),
                {"run_id": self.run_id},
            )
        ]
        assert "张三" in names
