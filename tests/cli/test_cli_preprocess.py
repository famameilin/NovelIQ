"""
CLI preprocess 模块测试

创建时间: 2025-03-11
创建者: TraeAI
任务: 测试预处理流程

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 使用 SessionFactory 替代 connect_db/create_tables，消除 DeprecationWarning，移除不存在的 split_by_chapter 参数

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration-cleanup
修改内容: 改用 PostgreSQL db_session fixture，移除 SQLite 依赖
"""
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.storage.repositories import ChunkRepository, RunRepository
from src.workflows.preprocess import run_preprocess


class MockEmbeddingClient:
    def __init__(self, *args, **kwargs):
        pass

    def get_embedding(self, text: str):
        import random
        return [random.random() for _ in range(768)]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        import random
        return [[random.random() for _ in range(768)] for _ in texts]

    @staticmethod
    def compute_similarity(vec1, vec2):
        return 0.5


class TestPreprocess:
    def _create_source_file(self, tmp: str, content: str = "测试文本内容。包含多个句子。") -> Path:
        source_path = Path(tmp) / f"novel_{uuid.uuid4().hex[:8]}.txt"
        source_path.write_text(content, encoding="utf-8")
        return source_path

    @pytest.mark.asyncio()
    @patch("src.chunking.chunker.EmbeddingClient", MockEmbeddingClient)
    async def test_preprocess_basic(self, db_session, tmp_path) -> None:
        source_path = self._create_source_file(str(tmp_path), "测试文本内容。" * 100)

        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=f"test_novel_{uuid.uuid4().hex[:8]}",
            source_path=str(source_path),
            title="Test Novel",
        )

        chunks_inserted, total_chars, _ = await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
            max_chars=500,
        )
        assert chunks_inserted > 0
        assert total_chars > 0

        chunk_repo = ChunkRepository(db_session)
        assert chunk_repo.is_preprocess_complete(run_id)

        rows = chunk_repo.fetch_chunk_texts(run_id)
        assert len(rows) == chunks_inserted

    @pytest.mark.asyncio()
    @patch("src.chunking.chunker.EmbeddingClient", MockEmbeddingClient)
    async def test_preprocess_empty_file(self, db_session, tmp_path) -> None:
        source_path = self._create_source_file(str(tmp_path), "")

        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=f"empty_novel_{uuid.uuid4().hex[:8]}",
            source_path=str(source_path),
            title="Empty Novel",
        )

        chunks_inserted, total_chars, _ = await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
            max_chars=500,
        )
        assert chunks_inserted == 0
        assert total_chars == 0

    @pytest.mark.asyncio()
    @patch("src.models.local.embedding.EmbeddingClient", MockEmbeddingClient)
    async def test_preprocess_chapter_split(self, db_session, tmp_path) -> None:
        content = "第一章 测试\n" + "内容" * 200 + "\n\n第二章 测试\n" + "内容" * 200
        source_path = self._create_source_file(str(tmp_path), content)

        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=f"chapter_novel_{uuid.uuid4().hex[:8]}",
            source_path=str(source_path),
            title="Chapter Novel",
        )

        chunks_inserted, total_chars, _ = await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
            max_chars=500,
        )
        assert chunks_inserted > 0

    @pytest.mark.asyncio()
    @patch("src.chunking.chunker.EmbeddingClient", MockEmbeddingClient)
    async def test_preprocess_resume(self, db_session, tmp_path) -> None:
        source_path = self._create_source_file(str(tmp_path), "测试文本内容。" * 100)

        run_repo = RunRepository(db_session)
        run_id = run_repo.create_run(
            novel_id=f"resume_novel_{uuid.uuid4().hex[:8]}",
            source_path=str(source_path),
            title="Resume Novel",
        )

        chunks1, _, _ = await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
            max_chars=500,
        )
        assert chunks1 > 0

        chunks2, _, _ = await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
            max_chars=500,
        )
        assert chunks2 == 0
