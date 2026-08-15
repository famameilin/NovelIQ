from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.api.models.events import StreamEvent
from src.chunking.chunker import Chunk, split_chunk_paragraphs, split_paragraphs
from src.preprocess.tokenize import tokenize
from src.storage.repositories import ChapterRepository, RunRepository
from src.storage.repositories.paragraph_repository import ParagraphRepository
from src.workflows.preprocess import (
    _generate_paragraph_embedding_rows,
    _generate_paragraph_embeddings,
    run_preprocess,
)
from tests.support.analysis_factories import insert_test_novel


def _insert_chapter_texts_and_paragraphs(session, chunks: list[Chunk]) -> tuple[str, str]:
    """
    创建 run 并写入 chunks 与段落事实源

    修改说明: 2026-08-14 段落事实源改造后 embedding 从 paragraphs 表读取，
    单测必须先落段落行（split_chunk_paragraphs 生成），再调用 embedding 生成函数；
    chunks 外键关联 analysis_runs，需要先建 run 记录

    Returns:
        (run_id, novel_id)：每次调用生成唯一 run_id，避免同会话内用例串数据
    """
    novel_id = uuid4().hex[:8]
    run_id = uuid4().hex
    insert_test_novel(novel_id, session=session)
    RunRepository(session).create_run(
        novel_id=novel_id,
        source_path=f"data/uploads/{novel_id}.txt",
        title="Embedding Test",
        run_id=run_id,
    )
    ChapterRepository(session).insert_chapter_texts(run_id, chunks)
    spans = split_chunk_paragraphs(chunks)
    spans = [replace(span, token_count=len(tokenize(span.text))) for span in spans]
    ParagraphRepository(session).insert_paragraphs(run_id, spans)
    session.commit()
    return run_id, novel_id


@pytest.mark.asyncio
async def test_generate_paragraph_embeddings_uses_paragraph_only(db_session) -> None:
    """
    RAG 粒度固定为一个自然段：只生成 paragraph embedding，不再生成 chunk embedding

    修改说明: 2026-08-14 段落事实源改造后 embedding 从 paragraphs 表读取，
    不再从 all_chunks 内存对象切段
    """
    chunks = [
        Chunk(index=7, text="第一段文本\n\n第二段文本", start=0, end=11, chapter_id=1),
    ]
    run_id, novel_id = _insert_chapter_texts_and_paragraphs(db_session, chunks)

    mock_client = MagicMock()
    mock_client.detect_embedding_dimension = AsyncMock(return_value=1024)
    mock_client.embed_texts = AsyncMock(return_value=[[0.5, 0.6], [0.7, 0.8]])

    with (
        patch("src.models.local.embedding.EmbeddingClient", return_value=mock_client) as mock_client_factory,
        patch("src.workflows.preprocess.ensure_paragraph_embeddings_schema") as mock_ensure_paragraph_schema,
        patch("src.storage.repositories.paragraph.insert_paragraph_embeddings") as mock_insert_paragraph_embeddings,
    ):
        inserted = await _generate_paragraph_embeddings(
            session=db_session,
            run_id=run_id,
        )

    assert inserted == 2
    mock_client_factory.assert_called_once()
    assert mock_client_factory.call_args.kwargs["token_usage_callback"] is not None
    # run 记录存在时 novel_id 从 analysis_runs 读取，与建 run 时一致
    assert mock_client_factory.call_args.kwargs["novel_id"] == novel_id
    mock_client.detect_embedding_dimension.assert_awaited_once()
    mock_ensure_paragraph_schema.assert_called_once()
    # 二期段落化：embedding 行只携带 paragraph_id + 向量（身份以 paragraphs 表为准）
    paragraph_rows = mock_insert_paragraph_embeddings.call_args.args[2]
    assert [row.paragraph_id for row in paragraph_rows] == [0, 1]
    assert [row.embedding_vector for row in paragraph_rows] == [[0.5, 0.6], [0.7, 0.8]]


@pytest.mark.asyncio
async def test_generate_paragraph_embeddings_skips_when_no_paragraphs(db_session) -> None:
    """
    2026-08-14 用于验证段落事实源为空时直接跳过 embedding 生成，
    不初始化 embedding client
    """
    mock_client = MagicMock()

    with (
        patch("src.models.local.embedding.EmbeddingClient", return_value=mock_client) as mock_client_factory,
        patch("src.workflows.preprocess.ensure_paragraph_embeddings_schema") as mock_ensure_paragraph_schema,
    ):
        inserted = await _generate_paragraph_embeddings(
            session=db_session,
            run_id="run-empty",
        )

    assert inserted == 0
    mock_client_factory.assert_not_called()
    mock_ensure_paragraph_schema.assert_not_called()


@pytest.mark.asyncio
async def test_generate_paragraph_embeddings_fails_fast_on_dimension_mismatch(db_session) -> None:
    chunks = [Chunk(index=1, text="测试文本", start=0, end=4, chapter_id=1)]
    run_id, _ = _insert_chapter_texts_and_paragraphs(db_session, chunks)

    mock_client = MagicMock()
    mock_client.detect_embedding_dimension = AsyncMock(return_value=1536)

    with (
        patch("src.models.local.embedding.EmbeddingClient", return_value=mock_client),
        patch("src.workflows.preprocess.ensure_paragraph_embeddings_schema") as mock_ensure_paragraph_schema,
    ):
        with pytest.raises(ValueError, match="dimension mismatch"):
            await _generate_paragraph_embeddings(
                session=db_session,
                run_id=run_id,
            )

    mock_client.embed_texts.assert_not_called()
    mock_ensure_paragraph_schema.assert_not_called()


@pytest.mark.asyncio
async def test_generate_paragraph_embeddings_fails_fast_when_embedding_client_init_fails(
    db_session,
) -> None:
    chunks = [Chunk(index=1, text="测试文本", start=0, end=4, chapter_id=1)]
    run_id, _ = _insert_chapter_texts_and_paragraphs(db_session, chunks)

    with (
        patch("src.models.local.embedding.EmbeddingClient", side_effect=ValueError("missing embedding config")),
        patch("src.workflows.preprocess.ensure_paragraph_embeddings_schema") as mock_ensure_paragraph_schema,
    ):
        with pytest.raises(RuntimeError, match="embedding client initialization failed"):
            await _generate_paragraph_embeddings(
                session=db_session,
                run_id=run_id,
            )

    mock_ensure_paragraph_schema.assert_not_called()


@pytest.mark.asyncio
async def test_generate_paragraph_embedding_rows_fails_fast_on_empty_embedding(db_session) -> None:
    chunks = [Chunk(index=7, text="第一段文本\n\n第二段文本", start=0, end=11, chapter_id=1)]
    run_id, _ = _insert_chapter_texts_and_paragraphs(db_session, chunks)

    mock_client = MagicMock()
    mock_client.embed_texts = AsyncMock(return_value=[[0.5, 0.6], []])

    with pytest.raises(RuntimeError, match="paragraph embeddings incomplete"):
        await _generate_paragraph_embedding_rows(
            embedding_client=mock_client,
            run_id=run_id,
            row_factory=lambda **kwargs: SimpleNamespace(**kwargs),
        )


@pytest.mark.asyncio
async def test_generate_paragraph_embedding_rows_emits_batch_progress(db_session) -> None:
    chunks = [Chunk(index=7, text="第一段文本\n\n第二段文本", start=0, end=11, chapter_id=1)]
    run_id, _ = _insert_chapter_texts_and_paragraphs(db_session, chunks)

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
        run_id=run_id,
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

    修改说明: 2026-08-14 split_paragraphs 返回 ParagraphSpan（不再是 (start, end, text) 三元组），
    断言改为属性访问
    """
    chunk = Chunk(index=1, text=" 第一段。\n\n第二段。  ", start=100, end=120, chapter_id=1)

    paragraphs = split_paragraphs(chunk.text)

    assert [(p.local_start_char, p.local_end_char, p.text) for p in paragraphs] == [
        (1, 5, "第一段。"),
        (7, 11, "第二段。"),
    ]


def test_split_paragraphs_single_newline_is_paragraph_boundary() -> None:
    """2026-08-08 用于验证单换行也算段落边界，每行一个自然段"""
    paragraphs = split_paragraphs("第一段。\n第二段。")
    assert [(p.local_start_char, p.local_end_char, p.text) for p in paragraphs] == [
        (0, 4, "第一段。"),
        (5, 9, "第二段。"),
    ]


def test_split_paragraphs_blank_lines_do_not_produce_empty_paragraphs() -> None:
    """连续空行不产生空段落，段落坐标保持真实原文位置"""
    text = "第一段。\n\n\n第二段。"
    paragraphs = split_paragraphs(text)
    assert [(p.local_start_char, p.local_end_char, p.text) for p in paragraphs] == [
        (0, 4, "第一段。"),
        (7, 11, "第二段。"),
    ]


def test_split_paragraphs_splits_oversized_paragraph_at_sentence_boundaries() -> None:
    """
    2026-08-08 用于验证无空行分隔的超长章节按句子边界切分，
    单段不超过 embedding 服务物理 batch 上限
    """
    text = ("第一句。" * 500) + "第二句。" * 200
    paragraphs = split_paragraphs(text)

    assert len(paragraphs) > 1
    assert all(len(p.text) <= 1500 for p in paragraphs)
    assert all(p.text.endswith("。") for p in paragraphs)
    joined = "".join(p.text for p in paragraphs)
    assert joined == text


def test_split_paragraphs_oversized_without_sentence_boundaries_falls_back_hard_cut() -> None:
    """2026-08-08 用于验证无句子边界可用的超长段落退化为固定字数硬切"""
    text = "字" * 4000
    paragraphs = split_paragraphs(text)

    assert len(paragraphs) > 1
    assert all(len(p.text) <= 1500 for p in paragraphs)
    assert "".join(p.text for p in paragraphs) == text


@pytest.mark.asyncio
async def test_run_preprocess_commits_before_entering_embedding_stage() -> None:
    mock_session = MagicMock()
    mock_chapter_repo = MagicMock()
    mock_chapter_repo.is_preprocess_complete.return_value = False
    embedding_stage_commit_counts: list[int] = []

    async def fake_generate_paragraph_embeddings(session, run_id, emitter=None) -> int:
        embedding_stage_commit_counts.append(session.commit.call_count)
        return 0

    with (
        patch("src.workflows.preprocess.ingest_path", return_value=[SimpleNamespace(text="测试文本")]),
        patch("src.workflows.preprocess.normalize_text", side_effect=lambda text: text),
        patch(
            "src.workflows.preprocess.chunk_documents_with_chapters",
            new=AsyncMock(return_value=([Chunk(index=1, text="测试文本", start=0, end=4, chapter_id=1)], [])),
        ),
        patch("src.workflows.preprocess.tokenize", return_value=["测试", "文本"]),
        patch("src.workflows.preprocess.ChapterRepository", return_value=mock_chapter_repo),
        patch("src.workflows.preprocess._generate_paragraph_embeddings", new=fake_generate_paragraph_embeddings),
        patch("src.workflows.preprocess.settings.models.paragraph_embedding.semantic_enabled", True),
        patch(
            "src.workflows.preprocess_helpers._load_all_lexicons_for_preprocess",
            return_value={"sensory": [], "function_words": [], "semantic_categories": {}, "imagery": []},
        ),
    ):
        inserted, _, _ = await run_preprocess(
            source_path=SimpleNamespace(),
            run_id="run-1",
            session=mock_session,
        )

    assert inserted == 1
    # 修改说明: 2026-08-14 段落事实源新增 insert_paragraphs 与段落指标
    # （insert_paragraph_metrics）、段落曲线（insert_paragraph_curves）分段提交；
    # M8b 删除 chunk_style 提交后，embedding 阶段前的提交数为 5
    # （chapters/chunks/paragraphs/paragraph_metrics/paragraph_curves）
    assert embedding_stage_commit_counts == [5]


@pytest.mark.asyncio
async def test_run_preprocess_passes_only_emitter_to_chunk_documents() -> None:
    """
    2026-08-05 用于验证预处理入口只向 chunk_documents_with_chapters 透传 emitter
    """
    mock_session = MagicMock()
    mock_chapter_repo = MagicMock()
    mock_chapter_repo.is_preprocess_complete.return_value = False
    mock_chunk_documents = AsyncMock(
        return_value=([Chunk(index=0, text="测试文本", start=0, end=4, chapter_id=1)], [])
    )

    with (
        patch("src.workflows.preprocess.ingest_path", return_value=[SimpleNamespace(text="测试文本")]),
        patch("src.workflows.preprocess.normalize_text", side_effect=lambda text: text),
        patch("src.workflows.preprocess.chunk_documents_with_chapters", new=mock_chunk_documents),
        patch("src.workflows.preprocess.tokenize", return_value=["测试", "文本"]),
        patch("src.workflows.preprocess.ChapterRepository", return_value=mock_chapter_repo),
        patch("src.workflows.preprocess.settings.models.paragraph_embedding.semantic_enabled", False),
        patch(
            "src.workflows.preprocess_helpers._load_all_lexicons_for_preprocess",
            return_value={"sensory": [], "function_words": [], "semantic_categories": {}, "imagery": []},
        ),
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
