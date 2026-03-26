"""
CLI annotate 妯″潡娴嬭瘯

鍒涘缓鏃堕棿: 2025-03-11
鍒涘缓鑰? TraeAI
浠诲姟: 娴嬭瘯鏍囨敞娴佺▼

淇敼鏃堕棿: 2026-03-15
淇敼鑰? TraeAI
浠诲姟: storage-layer-decoupling
淇敼鍐呭: 浣跨敤 SessionFactory 鏇夸唬 connect_db/create_tables锛屾秷闄?DeprecationWarning

淇敼鏃堕棿: 2026-03-15
淇敼鑰? TraeAI
浠诲姟: postgresql-migration
淇敼鍐呭: 浣跨敤 SQLAlchemy text() 鏇挎崲 ? 鍗犱綅绗︼紝绉婚櫎 sqlite3 瀵煎叆

淇敼鏃堕棿: 2026-03-15
淇敼鑰? TraeAI
浠诲姟: postgresql-migration-cleanup
淇敼鍐呭: 鏀圭敤 PostgreSQL db_session fixture锛岀Щ闄?SessionFactory 渚濊禆
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
from src.models.annotation import AnnotationClient
from src.models.disambiguation import DisambiguationClient
from src.models.local.schema import ChunkAnnotation, CharacterSnapshot, RelationChangeSnapshot, DialogueSnapshot
from src.models.local.annotation import MultiPhaseAnnotationResult
from src.models.local.disambiguation import ExtendedDisambigResult


def create_mock_annotation() -> MultiPhaseAnnotationResult:
    """
    鍒涘缓妯℃嫙鐨?MultiPhaseAnnotationResult

    淇敼鏃堕棿: 2026-03-18
    淇敼鑰? TraeAI
    浠诲姟: code-quality-refactor - 淇娴嬭瘯浠ラ€傚簲 MultiPhaseAnnotationResult 杩斿洖绫诲瀷
    """
    return MultiPhaseAnnotationResult(
        annotation=ChunkAnnotation(
            emotional_valence="neutral",
            event_type="閾哄灚",
            pivot_moment=False,
            cliffhanger=False,
            has_foreshadowing=False,
            foreshadowing_type=None,
            foreshadowing_desc="",
            characters=[
                CharacterSnapshot(
                    name="寮犱笁",
                    role_function="涓讳綋",
                    action="娴嬭瘯琛屼负",
                    action_type="鍏朵粬",
                    emotion_score="neutral",
                )
            ],
            relations=[
                RelationChangeSnapshot(
                    from_name="寮犱笁",
                    to_name="鏉庡洓",
                    type="鐩熷弸",
                    change="鏂板缓",
                )
            ],
            dialogues=[],
        ),
        foreshadowing=None,
        dialogue_lengths={"寮犱笁": 5},
        dialogue_speakers={0: "寮犱笁"},
        dialogues=[(1, "娴嬭瘯瀵硅瘽鍐呭")],
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
        chunks = [Chunk(index=i, start=0, end=10, text=f"寮犱笁鍦ㄦ祴璇曟枃鏈瑊i}涓鍔?) for i in range(chunk_count)]
        chunk_repo.insert_chunks(self.run_id, chunks)

    @patch("src.workflows.annotate_helpers.client_init.DisambiguationClient")
    @patch("src.workflows.annotate_helpers.client_init.AnnotationClient")
    def test_annotate_basic(self, mock_annotation_class: MagicMock, mock_disambiguation_class: MagicMock) -> None:
        mock_annotation_client = MagicMock(spec=AnnotationClient)
        mock_annotation_client.annotate_chunk.return_value = create_mock_annotation()
        mock_annotation_client._config = MagicMock(model="test-model", thinking_enabled=False)
        mock_disambiguation_client = MagicMock(spec=DisambiguationClient)
        mock_disambiguation_client.disambiguate_characters.return_value = ExtendedDisambigResult(
            merge_target_map={},
            entity_types={},
            entity_relations=[]
        )
        mock_annotation_class.return_value = mock_annotation_client
        mock_disambiguation_class.return_value = mock_disambiguation_client

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

    @patch("src.workflows.annotate_helpers.client_init.DisambiguationClient")
    @patch("src.workflows.annotate_helpers.client_init.AnnotationClient")
    def test_annotate_resume(self, mock_annotation_class: MagicMock, mock_disambiguation_class: MagicMock) -> None:
        mock_annotation_client = MagicMock(spec=AnnotationClient)
        mock_annotation_client.annotate_chunk.return_value = create_mock_annotation()
        mock_annotation_client._config = MagicMock(model="test-model", thinking_enabled=False)
        mock_disambiguation_client = MagicMock(spec=DisambiguationClient)
        mock_disambiguation_client.disambiguate_characters.return_value = ExtendedDisambigResult(
            merge_target_map={},
            entity_types={},
            entity_relations=[]
        )
        mock_annotation_class.return_value = mock_annotation_client
        mock_disambiguation_class.return_value = mock_disambiguation_client

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

    @patch("src.workflows.annotate_helpers.client_init.DisambiguationClient")
    @patch("src.workflows.annotate_helpers.client_init.AnnotationClient")
    def test_annotate_disambiguation(
        self, mock_annotation_class: MagicMock, mock_disambiguation_class: MagicMock
    ) -> None:
        mock_annotation_client = MagicMock(spec=AnnotationClient)
        mock_annotation_client.annotate_chunk.return_value = create_mock_annotation()
        mock_annotation_client._config = MagicMock(model="test-model", thinking_enabled=False)
        mock_disambiguation_client = MagicMock(spec=DisambiguationClient)
        mock_disambiguation_client.disambiguate_characters.return_value = ExtendedDisambigResult(
            merge_target_map={"寮犱笁涓?: "寮犱笁"},
            entity_types={},
            entity_relations=[]
        )
        mock_annotation_class.return_value = mock_annotation_client
        mock_disambiguation_class.return_value = mock_disambiguation_client

        self._create_chunks(2)

        success, errors, total = run_annotate(
            run_id=self.run_id,
            session=self.db_session,
            resume=False,
        )
        assert success == 2

        self.db_session.execute(
            text("INSERT INTO chunk_characters (chunk_id, name, role_function, action, action_type, emotion_score, run_id) VALUES (1, '寮犱笁涓?, '鍏朵粬', 'test', '鍏朵粬', 'neutral', :run_id)"),
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
        assert "寮犱笁" in names

