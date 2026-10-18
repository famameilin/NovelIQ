"""CLI preprocess 模块测试"""

import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from src.workflows.preprocess_readiness import is_preprocess_complete

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.storage.repositories import ChapterRepository, RunRepository
from src.workflows.preprocess import run_preprocess
from tests.support.analysis_factories import insert_test_novel


class MockEmbeddingClient:
    def __init__(self, *args, **kwargs):
        pass

    async def get_embedding(self, text: str, chunk_id: int | None = None):
        import random

        return [random.random() for _ in range(1024)]

    async def embed_texts(
        self,
        texts: list[str],
        *,
        progress_callback=None,
    ) -> list[list[float]]:
        
        import random

        return [[random.random() for _ in range(1024)] for _ in texts]

    async def detect_embedding_dimension(self, probe_text: str = "dimension probe") -> int:
        return 1024

    @staticmethod
    def compute_similarity(vec1, vec2):
        return 0.5


class MockEmbeddingClientPreprocess:
    def __init__(self, *args, **kwargs):
        pass

    async def get_embedding(self, text: str, chunk_id: int | None = None):
        import random

        return [random.random() for _ in range(1024)]

    async def embed_texts(
        self,
        texts: list[str],
        *,
        progress_callback=None,
    ) -> list[list[float]]:
        
        import random

        return [[random.random() for _ in range(1024)] for _ in texts]

    async def detect_embedding_dimension(self, probe_text: str = "dimension probe") -> int:
        return 1024

    @staticmethod
    def compute_similarity(vec1, vec2):
        return 0.5


class TestPreprocess:
    def _create_source_file(self, tmp: str, content: str = "测试文本内容。包含多个句子。") -> Path:
        source_path = Path(tmp) / f"novel_{uuid.uuid4().hex[:8]}.txt"
        source_path.write_text(content, encoding="utf-8")
        return source_path

    @pytest.mark.asyncio()
    @patch("src.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_basic(self, db_session, tmp_path) -> None:
        source_path = self._create_source_file(str(tmp_path), "测试文本内容。" * 100)

        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path=str(source_path),
            title="Test Novel",
        )

        chunks_inserted, total_chars, _ = await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
        )
        assert chunks_inserted > 0
        assert total_chars > 0

        chapter_repo = ChapterRepository(db_session)
        assert is_preprocess_complete(chapter_repo.session, run_id)

        rows = chapter_repo.fetch_chapter_texts(run_id)
        assert len(rows) == chunks_inserted

    @pytest.mark.asyncio()
    @patch("src.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_empty_file(self, db_session, tmp_path) -> None:
        source_path = self._create_source_file(str(tmp_path), "")

        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path=str(source_path),
            title="Empty Novel",
        )

        chunks_inserted, total_chars, _ = await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
        )
        assert chunks_inserted == 0
        assert total_chars == 0

    @pytest.mark.asyncio()
    @patch("src.embedding.EmbeddingClient", MockEmbeddingClient)
    async def test_preprocess_chapter_split(self, db_session, tmp_path) -> None:
        content = "第一章 测试\n" + "内容" * 200 + "\n\n第二章 测试\n" + "内容" * 200
        source_path = self._create_source_file(str(tmp_path), content)

        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path=str(source_path),
            title="Chapter Novel",
        )

        chunks_inserted, total_chars, _ = await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
        )
        assert chunks_inserted > 0

    @pytest.mark.asyncio()
    @patch("src.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_resume(self, db_session, tmp_path) -> None:
        source_path = self._create_source_file(str(tmp_path), "测试文本内容。" * 100)

        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = run_repo.create_run(
            novel_id=novel_id,
            source_path=str(source_path),
            title="Resume Novel",
        )

        chunks1, _, _ = await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
        )
        assert chunks1 > 0

        chunks2, _, _ = await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
        )
        assert chunks2 == 0
