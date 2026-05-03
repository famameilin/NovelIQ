from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.models.events import StreamEvent
from src.chunking.chunker import Chunk
from src.workflows.preprocess import (
    _generate_chunk_embeddings,
    _generate_paragraph_embedding_rows,
    _split_chunk_paragraphs,
    run_preprocess,
)


@pytest.mark.asyncio
async def test_generate_chunk_embeddings_uses_chunk_index_as_chunk_id() -> None:
    chunks = [
        Chunk(index=7, text="第一段文本", start=0, end=4),
        Chunk(index=8, text="第二段文本", start=5, end=9),
    ]
    mock_client = MagicMock()
    mock_client.detect_embedding_dimension = AsyncMock(return_value=1024)
    mock_client.get_embedding = AsyncMock(side_effect=[[0.1, 0.2], [0.3, 0.4]])
    mock_client.embed_texts = AsyncMock(return_value=[[0.5, 0.6], [0.7, 0.8]])

    with (
        patch("src.models.local.embedding.EmbeddingClient", return_value=mock_client),
        patch("src.workflows.preprocess.ensure_chunk_embeddings_schema") as mock_ensure_schema,
        patch("src.workflows.preprocess.ensure_paragraph_embeddings_schema") as mock_ensure_paragraph_schema,
        patch("src.storage.repositories.chunk.insert_chunk_embeddings") as mock_insert_embeddings,
        patch("src.storage.repositories.chunk.insert_paragraph_embeddings") as mock_insert_paragraph_embeddings,
    ):
        inserted = await _generate_chunk_embeddings(
            session=MagicMock(),
            run_id="run-1",
            all_chunks=chunks,
        )

    assert inserted == 2
    mock_client.detect_embedding_dimension.assert_awaited_once()
    mock_ensure_schema.assert_called_once()
    mock_ensure_paragraph_schema.assert_called_once()
    assert mock_client.get_embedding.await_args_list[0].kwargs["chunk_id"] == 7
    assert mock_client.get_embedding.await_args_list[1].kwargs["chunk_id"] == 8
    assert mock_insert_embeddings.call_args.args[2] == [
        (7, [0.1, 0.2]),
        (8, [0.3, 0.4]),
    ]
    paragraph_rows = mock_insert_paragraph_embeddings.call_args.args[2]
    assert [row.chunk_id for row in paragraph_rows] == [7, 8]
    assert [row.paragraph_text for row in paragraph_rows] == ["第一段文本", "第二段文本"]
    assert [row.local_start_char for row in paragraph_rows] == [0, 0]
    assert [row.global_start_char for row in paragraph_rows] == [0, 5]


@pytest.mark.asyncio
async def test_generate_chunk_embeddings_fails_fast_on_dimension_mismatch() -> None:
    mock_client = MagicMock()
    mock_client.detect_embedding_dimension = AsyncMock(return_value=1536)
    mock_client.get_embedding = AsyncMock()

    with (
        patch("src.models.local.embedding.EmbeddingClient", return_value=mock_client),
        patch("src.workflows.preprocess.ensure_chunk_embeddings_schema") as mock_ensure_schema,
        patch("src.workflows.preprocess.ensure_paragraph_embeddings_schema") as mock_ensure_paragraph_schema,
    ):
        with pytest.raises(ValueError, match="dimension mismatch"):
            await _generate_chunk_embeddings(
                session=MagicMock(),
                run_id="run-1",
                all_chunks=[Chunk(index=1, text="测试文本", start=0, end=4)],
            )

    mock_client.get_embedding.assert_not_called()
    mock_ensure_schema.assert_not_called()
    mock_ensure_paragraph_schema.assert_not_called()


@pytest.mark.asyncio
async def test_generate_chunk_embeddings_fails_fast_when_embedding_client_init_fails() -> None:
    """
    创建时间: 2026-04-24
    任务: fix-level3-embedding-init-failfast
    说明: paragraph rerank 已是 Level3 硬前提，EmbeddingClient 初始化失败时 preprocess 必须直接失败，
          不能再静默跳过并留下永久 not-ready 的 run。
    """
    with (
        patch("src.models.local.embedding.EmbeddingClient", side_effect=ValueError("missing embedding config")),
        patch("src.workflows.preprocess.ensure_chunk_embeddings_schema") as mock_ensure_schema,
        patch("src.workflows.preprocess.ensure_paragraph_embeddings_schema") as mock_ensure_paragraph_schema,
    ):
        with pytest.raises(RuntimeError, match="embedding client initialization failed"):
            await _generate_chunk_embeddings(
                session=MagicMock(),
                run_id="run-1",
                all_chunks=[Chunk(index=1, text="测试文本", start=0, end=4)],
            )

    mock_ensure_schema.assert_not_called()
    mock_ensure_paragraph_schema.assert_not_called()


@pytest.mark.asyncio
async def test_generate_chunk_embeddings_fails_fast_on_missing_chunk_embedding() -> None:
    """
    创建时间: 2026-04-24
    任务: fix-level3-embedding-partial-write
    说明: chunk embedding 缺失会破坏 Level3 粗召回边界，preprocess 不应继续落库部分结果。
    """
    mock_client = MagicMock()
    mock_client.detect_embedding_dimension = AsyncMock(return_value=1024)
    mock_client.get_embedding = AsyncMock(side_effect=[[0.1, 0.2], []])
    mock_client.embed_texts = AsyncMock()

    with (
        patch("src.models.local.embedding.EmbeddingClient", return_value=mock_client),
        patch("src.workflows.preprocess.ensure_chunk_embeddings_schema"),
        patch("src.workflows.preprocess.ensure_paragraph_embeddings_schema"),
        patch("src.storage.repositories.chunk.insert_chunk_embeddings") as mock_insert_embeddings,
        patch("src.storage.repositories.chunk.insert_paragraph_embeddings") as mock_insert_paragraph_embeddings,
    ):
        with pytest.raises(RuntimeError, match="chunk embeddings incomplete"):
            await _generate_chunk_embeddings(
                session=MagicMock(),
                run_id="run-1",
                all_chunks=[
                    Chunk(index=1, text="第一段文本", start=0, end=4),
                    Chunk(index=2, text="第二段文本", start=5, end=9),
                ],
            )

    mock_insert_embeddings.assert_not_called()
    mock_insert_paragraph_embeddings.assert_not_called()
    mock_client.embed_texts.assert_not_called()


@pytest.mark.asyncio
async def test_generate_chunk_embeddings_commits_before_emitting_progress() -> None:
    chunks = [
        Chunk(index=1, text="第一段文本", start=0, end=4),
        Chunk(index=2, text="第二段文本", start=5, end=9),
    ]
    mock_client = MagicMock()
    mock_client.detect_embedding_dimension = AsyncMock(return_value=1024)
    mock_client.get_embedding = AsyncMock(side_effect=[[0.1, 0.2], [0.3, 0.4]])
    mock_client.embed_texts = AsyncMock(return_value=[[0.5, 0.6], [0.7, 0.8]])
    mock_session = MagicMock()
    observed_commit_counts: list[int] = []

    async def record_event(event) -> None:
        observed_commit_counts.append(mock_session.commit.call_count)

    with (
        patch("src.models.local.embedding.EmbeddingClient", return_value=mock_client),
        patch("src.workflows.preprocess.ensure_chunk_embeddings_schema"),
        patch("src.workflows.preprocess.ensure_paragraph_embeddings_schema"),
        patch("src.storage.repositories.chunk.insert_chunk_embeddings"),
        patch("src.storage.repositories.chunk.insert_paragraph_embeddings"),
        patch("src.workflows.preprocess.settings.models.semantic_chunking.embedding_dim", 1024),
    ):
        inserted = await _generate_chunk_embeddings(
            session=mock_session,
            run_id="run-1",
            all_chunks=chunks,
            emitter=record_event,
        )

    assert inserted == 2
    assert mock_session.commit.call_count == 2
    assert observed_commit_counts[0] == 1


@pytest.mark.asyncio
async def test_generate_chunk_embeddings_emits_chunk_progress_with_chunk_scope_fields() -> None:
    """
    创建时间: 2026-04-28
    任务: fix-preprocess-progress-context-leak
    说明: chunk embedding 进度事件必须显式带上自己的 sub_stage/current/total，
          不能继续复用前一个 semantic chunking 子阶段留下来的上下文字段。
    """
    chunks = [
        Chunk(index=i, text=f"第{i}段文本", start=(i - 1) * 10, end=i * 10)
        for i in range(1, 12)
    ]
    mock_client = MagicMock()
    mock_client.detect_embedding_dimension = AsyncMock(return_value=1024)
    mock_client.get_embedding = AsyncMock(return_value=[0.1, 0.2])
    mock_client.embed_texts = AsyncMock(return_value=[[0.5, 0.6] for _ in chunks])
    emitted: list[StreamEvent] = []

    async def capture(event: StreamEvent) -> None:
        emitted.append(event)

    with (
        patch("src.models.local.embedding.EmbeddingClient", return_value=mock_client),
        patch("src.workflows.preprocess.ensure_chunk_embeddings_schema"),
        patch("src.workflows.preprocess.ensure_paragraph_embeddings_schema"),
        patch("src.storage.repositories.chunk.insert_chunk_embeddings"),
        patch("src.storage.repositories.chunk.insert_paragraph_embeddings"),
    ):
        await _generate_chunk_embeddings(
            session=MagicMock(),
            run_id="run-1",
            all_chunks=chunks,
            emitter=capture,
        )

    chunk_start_event = emitted[0]
    chunk_progress_events = [event for event in emitted if event.message.startswith("生成向量嵌入 ")]

    assert chunk_start_event.sub_stage == "chunk_embedding"
    assert chunk_start_event.current == 0
    assert chunk_start_event.total == 11
    assert chunk_progress_events[0].sub_stage == "chunk_embedding"
    assert chunk_progress_events[0].current == 1
    assert chunk_progress_events[0].total == 11


@pytest.mark.asyncio
async def test_generate_paragraph_embedding_rows_fails_fast_on_empty_embedding() -> None:
    """
    创建时间: 2026-04-24
    任务: fix-paragraph-embedding-partial-write
    说明: paragraph embedding 缺失会让 Level3 readiness 永远失败，preprocess 应在落库前直接报错。
    """
    mock_client = MagicMock()
    mock_client.embed_texts = AsyncMock(return_value=[[0.5, 0.6], []])

    with pytest.raises(RuntimeError, match="paragraph embeddings incomplete"):
        await _generate_paragraph_embedding_rows(
            embedding_client=mock_client,
            run_id="run-1",
            all_chunks=[Chunk(index=7, text="第一段文本\n\n第二段文本", start=0, end=11)],
            row_factory=lambda **kwargs: SimpleNamespace(**kwargs),
        )


@pytest.mark.asyncio
async def test_generate_paragraph_embedding_rows_emits_batch_progress() -> None:
    mock_client = MagicMock()

    async def fake_embed_texts(texts, *, progress_callback=None):
        if progress_callback is not None:
            await progress_callback(1, 2, len(texts))
            await progress_callback(2, 2, len(texts))
        return [[0.5, 0.6], [0.7, 0.8]]

    mock_client.embed_texts = AsyncMock(side_effect=fake_embed_texts)
    emitted: list[StreamEvent] = []

    async def capture(event: StreamEvent) -> None:
        emitted.append(event)

    rows = await _generate_paragraph_embedding_rows(
        embedding_client=mock_client,
        run_id="run-1",
        all_chunks=[Chunk(index=7, text="第一段文本\n\n第二段文本", start=0, end=11)],
        row_factory=lambda **kwargs: SimpleNamespace(**kwargs),
        emitter=capture,
    )

    assert len(rows) == 2
    assert len(emitted) == 2
    assert all(event.sub_stage == "paragraph_embedding" for event in emitted)
    assert emitted[0].current == 1
    assert emitted[0].total == 2
    assert emitted[0].sub_percent == 50.0
    assert emitted[1].sub_percent == 100.0


@pytest.mark.asyncio
async def test_generate_chunk_embeddings_does_not_insert_chunk_rows_before_paragraph_rows_ready() -> None:
    """
    创建时间: 2026-04-24
    任务: fix-paragraph-failfast-atomicity
    说明: paragraph rows 生成失败时，不应先把 chunk embeddings 暂存进当前 session。
    """
    chunks = [Chunk(index=7, text="第一段文本", start=0, end=4)]
    mock_client = MagicMock()
    mock_client.detect_embedding_dimension = AsyncMock(return_value=1024)
    mock_client.get_embedding = AsyncMock(return_value=[0.1, 0.2])
    mock_session = MagicMock()

    with (
        patch("src.models.local.embedding.EmbeddingClient", return_value=mock_client),
        patch("src.workflows.preprocess.ensure_chunk_embeddings_schema"),
        patch("src.workflows.preprocess.ensure_paragraph_embeddings_schema"),
        patch(
            "src.workflows.preprocess._generate_paragraph_embedding_rows",
            new=AsyncMock(side_effect=RuntimeError("paragraph embeddings incomplete")),
        ),
        patch("src.storage.repositories.chunk.insert_chunk_embeddings") as mock_insert_embeddings,
        patch("src.storage.repositories.chunk.insert_paragraph_embeddings") as mock_insert_paragraph_embeddings,
    ):
        with pytest.raises(RuntimeError, match="paragraph embeddings incomplete"):
            await _generate_chunk_embeddings(
                session=mock_session,
                run_id="run-1",
                all_chunks=chunks,
            )

    mock_insert_embeddings.assert_not_called()
    mock_insert_paragraph_embeddings.assert_not_called()
    mock_session.commit.assert_called_once()


def test_split_chunk_paragraphs_returns_chunk_local_offsets() -> None:
    """
    创建时间: 2026-04-24
    任务: level3-paragraph-rerank
    说明: paragraph offset 第一版定义为 chunk 内字符范围，避免误用为全文 offset。
    """
    chunk = Chunk(index=1, text=" 第一段。\n\n第二段。  ", start=100, end=120)

    paragraphs = _split_chunk_paragraphs(chunk)

    assert paragraphs == [(1, 5, "第一段。"), (7, 11, "第二段。")]


@pytest.mark.asyncio
async def test_run_preprocess_commits_before_entering_embedding_stage() -> None:
    mock_session = MagicMock()
    mock_chunk_repo = MagicMock()
    mock_chunk_repo.is_preprocess_complete.return_value = False
    embedding_stage_commit_counts: list[int] = []

    async def fake_generate_chunk_embeddings(session, run_id, all_chunks, emitter=None) -> int:
        embedding_stage_commit_counts.append(session.commit.call_count)
        return len(all_chunks)

    with (
        patch("src.workflows.preprocess.ingest_path", return_value=[SimpleNamespace(text="测试文本")]),
        patch("src.workflows.preprocess.normalize_text", side_effect=lambda text: text),
        patch(
            "src.workflows.preprocess.chunk_documents",
            new=AsyncMock(return_value=[Chunk(index=1, text="测试文本", start=0, end=4)]),
        ),
        patch("src.workflows.preprocess.tokenize", return_value=["测试", "文本"]),
        patch("src.workflows.preprocess.ChunkRepository", return_value=mock_chunk_repo),
        patch("src.workflows.preprocess._generate_chunk_embeddings", new=fake_generate_chunk_embeddings),
        patch("src.workflows.preprocess.settings.rag.embedding_enabled", True),
        patch("src.workflows.preprocess.settings.rag.level3_enabled", True),
        patch("src.workflows.preprocess.settings.chunking.use_semantic_chunking", False),
        patch(
            "src.workflows.preprocess_helpers._load_all_lexicons_for_preprocess",
            return_value={"sensory": [], "function_words": [], "semantic_categories": {}, "imagery": []},
        ),
        patch("src.workflows.preprocess_helpers._compute_chunk_style_metrics", return_value=MagicMock()),
    ):
        inserted, _, _ = await run_preprocess(
            source_path=SimpleNamespace(),
            run_id="run-1",
            session=mock_session,
        )

    assert inserted == 1
    assert embedding_stage_commit_counts == [2]
