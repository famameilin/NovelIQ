"""原文关键词检索服务单元测试（二期段落化）"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.chunking.chunker import Chunk, split_chunk_paragraphs
from src.preprocess.tokenize import tokenize
from src.storage.repositories.paragraph.embedding_ops import SimilarParagraphRow
from src.storage.repositories.paragraph_repository import ParagraphRepository
from src.text_search.service import TextSearchService, extract_query_terms
from tests.support.chapter_annotation_helpers import create_run_with_chunks


def _insert_paragraphs(db_session, run_id: str, texts: list[str]) -> None:
    """2026-08-14 二期段落化：检索直接扫 paragraphs 表，测试须先落段落事实源"""
    offset = 0
    chunks = []
    for chunk_id, text in enumerate(texts):
        chunks.append(Chunk(index=chunk_id, text=text, start=offset, end=offset + len(text), chapter_id=1))
        offset += len(text)
    spans = split_chunk_paragraphs(chunks)
    spans = [replace(span, token_count=len(tokenize(span.text))) for span in spans]
    ParagraphRepository(db_session).insert_paragraphs(run_id, spans)
    db_session.commit()


def test_extract_query_terms_keeps_short_whole_query() -> None:
    """2026-08-12 用于验证短查询（无分隔符）保留整句词项"""
    assert extract_query_terms("顾霜入城") == ["顾霜入城"]


def test_extract_query_terms_splits_by_punctuation() -> None:
    """2026-08-12 用于验证长查询按标点/空格切分并保留拆分词项"""
    query = "顾霜，林渡。入城！哪里？他们去了南方，寻找真相。"
    result = extract_query_terms(query)
    assert "顾霜" in result
    assert "林渡" in result
    assert "入城" in result
    assert "寻找真相" in result
    assert query not in result


def test_extract_query_terms_long_query_without_separators_returns_empty() -> None:
    """2026-08-12 用于验证超过长度上限且无分隔符的查询不产生整句词项"""
    assert extract_query_terms("这是一段超过二十个字符长度没有分隔符的完整查询文本内容") == []


def test_extract_query_terms_long_query_with_separators_keeps_terms() -> None:
    """2026-08-12 用于验证长查询有分隔符时仅保留拆分词项"""
    query = "这段开篇正文足够长超过了阈值，顾霜、林渡在哪里。"
    result = extract_query_terms(query)
    assert "这段开篇正文足够长超过了阈值" in result
    assert "顾霜" in result
    assert "林渡在哪里" in result
    assert query not in result


def test_extract_query_terms_normalizes_and_dedupes() -> None:
    """2026-08-12 用于验证 NFC 归一化、小写与去重"""
    assert extract_query_terms(" 顾霜，顾霜 林渡 ") == ["顾霜，顾霜 林渡", "顾霜", "林渡"]


def test_extract_query_terms_empty_or_blank() -> None:
    """2026-08-12 用于验证空查询与纯空白查询返回空列表"""
    assert extract_query_terms("") == []
    assert extract_query_terms("   ") == []


@pytest.mark.asyncio
async def test_search_with_empty_query_returns_empty() -> None:
    """2026-08-12 用于验证空白查询直接返回空结果"""
    service = TextSearchService(MagicMock(), run_id="run-1")
    assert await service.search("   ") == []


@pytest.mark.asyncio
async def test_search_with_no_terms_skips_keyword_scan() -> None:
    """2026-08-12 用于验证长句无分隔符查询产生空词项，关键词检索接收空列表且不命中"""
    session = MagicMock()
    session.execute.return_value.all.return_value = []
    service = TextSearchService(session, run_id="run-1", semantic_enabled=False)
    with patch(
        "src.text_search.service.search_paragraphs_by_keywords",
        return_value=[],
    ) as mock_keyword:
        result = await service.search("这是一段超过二十个字符长度没有分隔符的完整查询文本内容")

    mock_keyword.assert_called_once()
    assert mock_keyword.call_args.args[2] == []
    assert result == []


@pytest.mark.asyncio
async def test_search_returns_separate_candidates_for_paragraphs_in_same_chapter(db_session) -> None:
    """2026-08-14 二期段落化（§18.4）：同一 chunk/章的多个命中段落不再按 chunk 合并，
    每个段落都是独立候选"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜并肩迎敌，携手入城。\n顾霜独自离去。"],
        title="段落候选不合并",
    )
    _insert_paragraphs(db_session, run_id, ["林渡与顾霜并肩迎敌，携手入城。\n顾霜独自离去。"])
    service = TextSearchService(db_session, run_id=run_id, semantic_enabled=False)

    result = await service.search("林渡 顾霜")

    assert len(result) == 2
    by_paragraph = {candidate.paragraph_id: candidate for candidate in result}
    assert set(by_paragraph) == {0, 1}
    assert by_paragraph[0].excerpt == "林渡与顾霜并肩迎敌，携手入城。"
    assert by_paragraph[0].keyword_score == 2.0
    assert by_paragraph[1].excerpt == "顾霜独自离去。"
    assert by_paragraph[1].keyword_score == 1.0
    # 排序：(-semantic_score, -keyword_score, paragraph_id)
    assert [candidate.paragraph_id for candidate in result] == [0, 1]
    assert all(candidate.chapter_id == 1 for candidate in result)
    # 坐标来自 paragraphs 事实源列
    assert by_paragraph[0].local_start_char == 0
    assert by_paragraph[0].global_start_char == 0
    assert by_paragraph[1].local_start_char == 16


@pytest.mark.asyncio
async def test_search_merges_keyword_and_semantic_scores_per_paragraph(db_session) -> None:
    """2026-08-14 二期段落化：同一段落 keyword+semantic 都命中时合并为一条候选"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜并肩迎敌，携手入城。\n顾霜独自离去。"],
        title="段落双分合并",
    )
    _insert_paragraphs(db_session, run_id, ["林渡与顾霜并肩迎敌，携手入城。\n顾霜独自离去。"])
    service = TextSearchService(db_session, run_id=run_id, semantic_enabled=True)
    service._embedding_client = AsyncMock()
    semantic_rows = [
        SimilarParagraphRow(
            paragraph_id=0,
            chapter_id=1,
            paragraph_text="林渡与顾霜并肩迎敌，携手入城。",
            local_start_char=0,
            local_end_char=15,
            global_start_char=0,
            global_end_char=15,
            similarity=0.9,
        )
    ]
    with patch(
        "src.text_search.service.search_similar_paragraphs",
        return_value=semantic_rows,
    ):
        result = await service.search("林渡 顾霜")

    by_paragraph = {candidate.paragraph_id: candidate for candidate in result}
    assert set(by_paragraph) == {0, 1}
    # 段落 0：keyword（林渡+顾霜=2.0）与 semantic（0.9）合并进一条候选
    candidate = by_paragraph[0]
    assert candidate.keyword_score == 2.0
    assert candidate.semantic_score == 0.9
    assert candidate.excerpt == "林渡与顾霜并肩迎敌，携手入城。"
    # 段落 1：只有 keyword 命中（顾霜），保持独立候选
    assert by_paragraph[1].keyword_score == 1.0
    assert by_paragraph[1].semantic_score is None


@pytest.mark.asyncio
async def test_search_respects_paragraph_bounds(db_session) -> None:
    """2026-08-14 二期段落化：min/max 边界按 paragraph_id 过滤"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜并肩迎敌，携手入城。\n顾霜独自离去。"],
        title="段落边界",
    )
    _insert_paragraphs(db_session, run_id, ["林渡与顾霜并肩迎敌，携手入城。\n顾霜独自离去。"])
    service = TextSearchService(db_session, run_id=run_id, semantic_enabled=False)

    result = await service.search("顾霜", min_paragraph_id=1)

    assert [candidate.paragraph_id for candidate in result] == [1]
    assert result[0].excerpt == "顾霜独自离去。"


@pytest.mark.asyncio
async def test_read_returns_target_with_context_paragraphs(db_session) -> None:
    """2026-08-14 二期段落化：read 按 paragraph_id 读段落，默认带前后各一段上下文"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["第一段。\n第二段。\n第三段。"],
        title="上下文读取",
    )
    _insert_paragraphs(db_session, run_id, ["第一段。\n第二段。\n第三段。"])
    service = TextSearchService(db_session, run_id=run_id, semantic_enabled=False)

    # context_paragraphs=1：目标段 + 前后各一段，换行分隔
    assert service.read(1) == "第一段。\n第二段。\n第三段。"
    # context_paragraphs=0：只返回目标段
    assert service.read(1, context_paragraphs=0) == "第二段。"
    # 边界截断：首段无前文
    assert service.read(0) == "第一段。\n第二段。"
    assert service.read(2) == "第二段。\n第三段。"
    with pytest.raises(ValueError, match="原文段落不存在或跨 run"):
        service.read(999)


@pytest.mark.asyncio
async def test_search_with_missing_paragraph_meta_skips_candidate(db_session) -> None:
    """2026-08-14 二期段落化：候选段落元数据（章节/chunk）查不到时跳过该候选"""
    session = MagicMock()
    session.execute.return_value.all.return_value = []
    service = TextSearchService(session, run_id="run-1", semantic_enabled=False)
    keyword_row = MagicMock(
        paragraph_id=7,
        paragraph_text="顾霜入城。",
        match_count=1,
        local_start_char=0,
        local_end_char=5,
        global_start_char=0,
        global_end_char=5,
    )
    with patch(
        "src.text_search.service.search_paragraphs_by_keywords",
        return_value=[keyword_row],
    ):
        result = await service.search("顾霜")

    assert result == []
