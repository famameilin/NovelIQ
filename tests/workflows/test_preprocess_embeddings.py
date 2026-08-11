from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.models.events import StreamEvent
from src.chunking.chunker import Chunk, split_paragraphs
from src.workflows.preprocess import (
    _generate_paragraph_embedding_rows,
    _generate_paragraph_embeddings,
    run_preprocess,
)


@pytest.mark.asyncio
async def test_generate_paragraph_embeddings_uses_paragraph_only() -> None:
    """
    RAG 粒度固定为一个自然段：只生成 paragraph embedding，不再生成 chunk embedding
    """
    chunks = [
        Chunk(index=7, text="第一段文本\n\n第二段文本", start=0, end=11, chapter_id=1),
    ]
    mock_client = MagicMock()
    mock_client.detect_embedding_dimension = AsyncMock(return_value=1024)
    mock_client.embed_texts = AsyncMock(return_value=[[0.5, 0.6], [0.7, 0.8]])

    with (
        patch("src.models.local.embedding.EmbeddingClient", return_value=mock_client) as mock_client_factory,
        patch("src.workflows.preprocess.ensure_paragraph_embeddings_schema") as mock_ensure_paragraph_schema,
        patch("src.storage.repositories.chunk.insert_paragraph_embeddings") as mock_insert_paragraph_embeddings,
    ):
        inserted = await _generate_paragraph_embeddings(
            session=MagicMock(),
            run_id="run-1",
            all_chunks=chunks,
        )

    assert inserted == 2
    mock_client_factory.assert_called_once()
    assert mock_client_factory.call_args.kwargs["token_usage_callback"] is not None
    assert mock_client_factory.call_args.kwargs["novel_id"] == "unknown"
    mock_client.detect_embedding_dimension.assert_awaited_once()
    mock_ensure_paragraph_schema.assert_called_once()
    paragraph_rows = mock_insert_paragraph_embeddings.call_args.args[2]
    assert [row.chunk_id for row in paragraph_rows] == [7, 7]
    assert [row.paragraph_text for row in paragraph_rows] == ["第一段文本", "第二段文本"]
    assert [row.local_start_char for row in paragraph_rows] == [0, 7]
    assert [row.global_start_char for row in paragraph_rows] == [0, 7]


@pytest.mark.asyncio
async def test_generate_paragraph_embeddings_fails_fast_on_dimension_mismatch() -> None:
    mock_client = MagicMock()
    mock_client.detect_embedding_dimension = AsyncMock(return_value=1536)

    with (
        patch("src.models.local.embedding.EmbeddingClient", return_value=mock_client),
        patch("src.workflows.preprocess.ensure_paragraph_embeddings_schema") as mock_ensure_paragraph_schema,
    ):
        with pytest.raises(ValueError, match="dimension mismatch"):
            await _generate_paragraph_embeddings(
                session=MagicMock(),
                run_id="run-1",
                all_chunks=[Chunk(index=1, text="测试文本", start=0, end=4, chapter_id=1)],
            )

    mock_client.embed_texts.assert_not_called()
    mock_ensure_paragraph_schema.assert_not_called()


@pytest.mark.asyncio
async def test_generate_paragraph_embeddings_fails_fast_when_embedding_client_init_fails() -> None:
    with (
        patch("src.models.local.embedding.EmbeddingClient", side_effect=ValueError("missing embedding config")),
        patch("src.workflows.preprocess.ensure_paragraph_embeddings_schema") as mock_ensure_paragraph_schema,
    ):
        with pytest.raises(RuntimeError, match="embedding client initialization failed"):
            await _generate_paragraph_embeddings(
                session=MagicMock(),
                run_id="run-1",
                all_chunks=[Chunk(index=1, text="测试文本", start=0, end=4, chapter_id=1)],
            )

    mock_ensure_paragraph_schema.assert_not_called()


@pytest.mark.asyncio
async def test_generate_paragraph_embedding_rows_fails_fast_on_empty_embedding() -> None:
    mock_client = MagicMock()
    mock_client.embed_texts = AsyncMock(return_value=[[0.5, 0.6], []])

    with pytest.raises(RuntimeError, match="paragraph embeddings incomplete"):
        await _generate_paragraph_embedding_rows(
            embedding_client=mock_client,
            run_id="run-1",
            all_chunks=[Chunk(index=7, text="第一段文本\n\n第二段文本", start=0, end=11, chapter_id=1)],
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
        all_chunks=[Chunk(index=7, text="第一段文本\n\n第二段文本", start=0, end=11, chapter_id=1)],
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


def test_split_paragraphs_returns_chunk_local_offsets() -> None:
    """
    自然段按空行切分，不再按单行切分
    """
    chunk = Chunk(index=1, text=" 第一段。\n\n第二段。  ", start=100, end=120, chapter_id=1)

    paragraphs = split_paragraphs(chunk.text)

    assert paragraphs == [(1, 5, "第一段。"), (7, 11, "第二段。")]


def test_split_paragraphs_single_newline_is_paragraph_boundary() -> None:
    """2026-08-08 用于验证单换行也算段落边界，每行一个自然段"""
    paragraphs = split_paragraphs("第一段。\n第二段。")
    assert paragraphs == [(0, 4, "第一段。"), (5, 9, "第二段。")]


def test_split_paragraphs_blank_lines_do_not_produce_empty_paragraphs() -> None:
    """连续空行不产生空段落，段落坐标保持真实原文位置"""
    text = "第一段。\n\n\n第二段。"
    paragraphs = split_paragraphs(text)
    assert paragraphs == [(0, 4, "第一段。"), (7, 11, "第二段。")]


def test_split_paragraphs_splits_oversized_paragraph_at_sentence_boundaries() -> None:
    """
    2026-08-08 用于验证无空行分隔的超长章节按句子边界切分，
    单段不超过 embedding 服务物理 batch 上限
    """
    text = ("第一句。" * 500) + "第二句。" * 200
    paragraphs = split_paragraphs(text)

    assert len(paragraphs) > 1
    assert all(len(paragraph) <= 1500 for _, _, paragraph in paragraphs)
    assert all(paragraph.endswith("。") for _, _, paragraph in paragraphs)
    joined = "".join(paragraph for _, _, paragraph in paragraphs)
    assert joined == text


def test_split_paragraphs_oversized_without_sentence_boundaries_falls_back_hard_cut() -> None:
    """2026-08-08 用于验证无句子边界可用的超长段落退化为固定字数硬切"""
    text = "字" * 4000
    paragraphs = split_paragraphs(text)

    assert len(paragraphs) > 1
    assert all(len(paragraph) <= 1500 for _, _, paragraph in paragraphs)
    assert "".join(paragraph for _, _, paragraph in paragraphs) == text


@pytest.mark.asyncio
async def test_run_preprocess_commits_before_entering_embedding_stage() -> None:
    mock_session = MagicMock()
    mock_chunk_repo = MagicMock()
    mock_chunk_repo.is_preprocess_complete.return_value = False
    embedding_stage_commit_counts: list[int] = []

    async def fake_generate_paragraph_embeddings(session, run_id, all_chunks, emitter=None) -> int:
        embedding_stage_commit_counts.append(session.commit.call_count)
        return len(all_chunks)

    with (
        patch("src.workflows.preprocess.ingest_path", return_value=[SimpleNamespace(text="测试文本")]),
        patch("src.workflows.preprocess.normalize_text", side_effect=lambda text: text),
        patch(
            "src.workflows.preprocess.chunk_documents_with_chapters",
            new=AsyncMock(return_value=([Chunk(index=1, text="测试文本", start=0, end=4, chapter_id=1)], [])),
        ),
        patch("src.workflows.preprocess.tokenize", return_value=["测试", "文本"]),
        patch("src.workflows.preprocess.ChunkRepository", return_value=mock_chunk_repo),
        patch("src.workflows.preprocess.ChapterRepository", return_value=MagicMock()),
        patch("src.workflows.preprocess._generate_paragraph_embeddings", new=fake_generate_paragraph_embeddings),
        patch("src.workflows.preprocess.settings.models.paragraph_embedding.semantic_enabled", True),
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
    assert embedding_stage_commit_counts == [3]


@pytest.mark.asyncio
async def test_run_preprocess_passes_only_emitter_to_chunk_documents() -> None:
    """
    2026-08-05 用于验证预处理入口只向 chunk_documents_with_chapters 透传 emitter
    """
    mock_session = MagicMock()
    mock_chunk_repo = MagicMock()
    mock_chunk_repo.is_preprocess_complete.return_value = False
    mock_chunk_documents = AsyncMock(
        return_value=([Chunk(index=0, text="测试文本", start=0, end=4, chapter_id=1)], [])
    )

    with (
        patch("src.workflows.preprocess.ingest_path", return_value=[SimpleNamespace(text="测试文本")]),
        patch("src.workflows.preprocess.normalize_text", side_effect=lambda text: text),
        patch("src.workflows.preprocess.chunk_documents_with_chapters", new=mock_chunk_documents),
        patch("src.workflows.preprocess.tokenize", return_value=["测试", "文本"]),
        patch("src.workflows.preprocess.ChunkRepository", return_value=mock_chunk_repo),
        patch("src.workflows.preprocess.ChapterRepository", return_value=MagicMock()),
        patch("src.workflows.preprocess.settings.models.paragraph_embedding.semantic_enabled", False),
        patch(
            "src.workflows.preprocess_helpers._load_all_lexicons_for_preprocess",
            return_value={"sensory": [], "function_words": [], "semantic_categories": {}, "imagery": []},
        ),
        patch("src.workflows.preprocess_helpers._compute_chunk_style_metrics", return_value=MagicMock()),
    ):
        await run_preprocess(
            source_path=SimpleNamespace(),
            run_id="run-1",
            session=mock_session,
        )

    call_kwargs = mock_chunk_documents.await_args.kwargs
    assert "max_chars" not in call_kwargs
    assert "start_chars" not in call_kwargs
    assert call_kwargs.get("emitter") is None
