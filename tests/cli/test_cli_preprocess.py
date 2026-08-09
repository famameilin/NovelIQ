"""
CLI preprocess 模块测试

创建时间: 2025-03-11
任务: 测试预处理流程

修改时间: 2026-03-15
任务: storage-layer-decoupling
修改内容: 使用 SessionFactory 替代 connect_db/create_tables，消除 DeprecationWarning，移除不存在的 split_by_chapter 参数

修改时间: 2026-03-15
任务: postgresql-migration-cleanup
修改内容: 改用 PostgreSQL db_session fixture，移除 SQLite 依赖
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.storage.models import Novel
from src.storage.repositories import ChunkRepository, RunRepository
from src.workflows.preprocess import run_preprocess


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
        """
        修改时间: 2026-04-27
        任务: fix-preprocess-progress-callback-tests
        修改内容: 对齐 EmbeddingClient.embed_texts 的 progress_callback 可选参数，
        避免 preprocess 新增 SSE 进度透传后测试桩签名落后。
        """
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
        """
        修改时间: 2026-04-27
        任务: fix-preprocess-progress-callback-tests
        修改内容: 对齐 preprocess paragraph embedding 新增的 progress_callback 参数，
        让 CLI 回归测试继续覆盖真实入口而不是被 mock 签名拦住。
        """
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
    @patch("src.models.local.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_basic(self, db_session, tmp_path) -> None:
        source_path = self._create_source_file(str(tmp_path), "测试文本内容。" * 100)

        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, novel_id)
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

        chunk_repo = ChunkRepository(db_session)
        assert chunk_repo.is_preprocess_complete(run_id)

        rows = chunk_repo.fetch_chunk_texts(run_id)
        assert len(rows) == chunks_inserted

    @pytest.mark.asyncio()
    @patch("src.models.local.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_empty_file(self, db_session, tmp_path) -> None:
        source_path = self._create_source_file(str(tmp_path), "")

        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, novel_id)
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
    @patch("src.models.local.embedding.EmbeddingClient", MockEmbeddingClient)
    async def test_preprocess_chapter_split(self, db_session, tmp_path) -> None:
        content = "第一章 测试\n" + "内容" * 200 + "\n\n第二章 测试\n" + "内容" * 200
        source_path = self._create_source_file(str(tmp_path), content)

        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, novel_id)
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
    @patch("src.models.local.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_resume(self, db_session, tmp_path) -> None:
        source_path = self._create_source_file(str(tmp_path), "测试文本内容。" * 100)

        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        _insert_test_novel(db_session, novel_id)
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
