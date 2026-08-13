"""原文关键词检索服务单元测试"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.text_search.service import TextSearchService, extract_query_terms


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
async def test_search_excerpt_keeps_highest_match_paragraph(db_session) -> None:
    """2026-08-13 P1-4 用于验证同一 chunk 多段落命中时 excerpt 取 match_count 最高的段落

    修复前 rows 已按 match_count 降序，但 service 按 chunk_id 后写覆盖，
    同 chunk 内弱匹配段（段落 2）会盖掉强匹配段（段落 1）成为 excerpt。
    """
    from tests.support.chapter_annotation_helpers import create_run_with_chunks

    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["林渡与顾霜并肩迎敌，携手入城。\n顾霜独自离去。"],
        title="excerpt 择优",
    )
    service = TextSearchService(db_session, run_id=run_id, semantic_enabled=False)

    result = await service.search("林渡 顾霜")

    assert len(result) == 1
    candidate = result[0]
    assert candidate.excerpt == "林渡与顾霜并肩迎敌，携手入城。"
    assert candidate.keyword_score == 2.0
