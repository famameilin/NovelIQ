from types import SimpleNamespace
from unittest.mock import MagicMock

from src.storage.repositories.chunk.keyword_ops import (
    KeywordMatchRow,
    fetch_chunk_text,
    search_paragraphs_by_keywords,
)


def test_search_paragraphs_by_keywords_orders_by_match_count() -> None:
    """
    2026-08-02 用于验证关键词检索结果保留命中数量与原文定位
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            chunk_id=3,
            char_offset=100,
            text="赤羽炽尾鸡被阵法镇压，猴子去拔尾羽。",
        ),
        SimpleNamespace(
            chunk_id=1,
            char_offset=10,
            text="赤羽炽尾鸡是灵兽。",
        ),
    ]

    results = search_paragraphs_by_keywords(
        session,
        run_id="run-1",
        keywords=["赤羽炽尾鸡", "阵法", "猴子"],
        top_k=5,
    )

    assert [r.chunk_id for r in results] == [3, 1]
    assert results[0].match_count == 3
    assert results[0].matched_keywords == ("赤羽炽尾鸡", "阵法", "猴子")
    assert results[0].global_start_char == 100


def test_search_paragraphs_by_keywords_filters_non_matching_rows() -> None:
    """
    2026-08-02 用于过滤数据库替身返回的非字面命中段落
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            chunk_id=2,
            char_offset=50,
            text="普通段落没有命中词。",
        ),
    ]

    results = search_paragraphs_by_keywords(
        session,
        run_id="run-1",
        keywords=["不存在词"],
        top_k=5,
    )

    assert results == []


def test_search_paragraphs_by_keywords_rejects_empty_keywords() -> None:
    """
    2026-08-02 用于拒绝空关键词请求且不访问数据库
    """
    session = MagicMock()

    results = search_paragraphs_by_keywords(session, run_id="run-1", keywords=["  ", ""], top_k=5)

    assert results == []
    session.execute.assert_not_called()


def test_search_paragraphs_by_keywords_pushes_bounds_into_sql() -> None:
    """
    2026-08-02 用于保证历史边界与排除条件进入 SQL 查询
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = []

    search_paragraphs_by_keywords(
        session,
        run_id="run-1",
        keywords=["叶文洁"],
        top_k=3,
        exclude_chunk_ids=[5],
        max_chunk_id=10,
    )

    stmt = session.execute.call_args.args[0]
    assert stmt._where_criteria


def test_search_paragraphs_by_keywords_escapes_sql_wildcards_and_deduplicates() -> None:
    """
    2026-08-02 用于保证百分号下划线按字面子串匹配且重复关键词不重复计分
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            chunk_id=2,
            char_offset=50,
            text="完成度达到100%，代号为A_B。",
        ),
    ]

    results = search_paragraphs_by_keywords(
        session,
        run_id="run-1",
        keywords=["100%", "A_B", "100%"],
        top_k=5,
    )

    stmt = session.execute.call_args.args[0]
    compiled_sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "ESCAPE" in compiled_sql
    assert len(results) == 1
    # 2026-08-13 P2-6：词项统一小写归一后 matched_keywords 保留小写形式
    assert results[0].matched_keywords == ("100%", "a_b")
    assert results[0].match_count == 2


def test_search_paragraphs_by_keywords_counts_unmatched_chunks_for_fallback_offsets() -> None:
    """
    2026-08-04 用于保证缺失存储偏移时仍累计中间未命中 chunk 的原文长度
    """
    session = MagicMock()
    matching_rows = [
        SimpleNamespace(chunk_id=3, char_offset=None, char_end_offset=None, text="命中目标段落。"),
    ]
    all_rows = [
        SimpleNamespace(chunk_id=1, char_offset=None, char_end_offset=None, text="前置文本。"),
        SimpleNamespace(chunk_id=2, char_offset=None, char_end_offset=None, text="中间文本。"),
        SimpleNamespace(chunk_id=3, char_offset=None, char_end_offset=None, text="命中目标段落。"),
    ]
    session.execute.side_effect = [
        MagicMock(all=MagicMock(return_value=matching_rows)),
        MagicMock(all=MagicMock(return_value=all_rows)),
    ]

    results = search_paragraphs_by_keywords(session, run_id="run-1", keywords=["目标"], top_k=5)

    assert len(results) == 1
    assert results[0].global_start_char == len("前置文本。") + len("中间文本。")
    assert session.execute.call_count == 2


def test_fetch_chunk_text_returns_text_when_present() -> None:
    """
    2026-08-02 用于返回存在的历史 chunk 原文
    """
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = "完整章节原文。"

    text = fetch_chunk_text(session, run_id="run-1", chunk_id=3)

    assert text == "完整章节原文。"


def test_fetch_chunk_text_returns_none_when_missing() -> None:
    """
    2026-08-02 用于在历史 chunk 不存在时返回 None
    """
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    text = fetch_chunk_text(session, run_id="run-1", chunk_id=99)

    assert text is None


def test_search_paragraphs_by_keywords_matches_case_insensitively() -> None:
    """
    2026-08-13 P2-6 用于验证查询词项（已小写）能命中大小写混合的原文，
    SQL LIKE 与 Python 侧子串匹配都做 lower 归一，英文词不再因大小写漏命中。
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            chunk_id=2,
            char_offset=50,
            text="顾霜持 Sword 现身，Sword 寒光凛冽。",
        ),
    ]

    results = search_paragraphs_by_keywords(
        session,
        run_id="run-1",
        keywords=["sword"],
        top_k=5,
    )

    stmt = session.execute.call_args.args[0]
    compiled_sql = str(stmt.compile())
    assert "lower(chunks.text) LIKE" in compiled_sql
    assert len(results) == 1
    assert results[0].matched_keywords == ("sword",)
    assert results[0].match_count == 1


def test_keyword_match_row_is_frozen_dataclass() -> None:
    """
    2026-08-02 用于锁定关键词命中 DTO 的不可变结构
    """
    row = KeywordMatchRow(
        chunk_id=1,
        paragraph_index=0,
        paragraph_text="文本",
        local_start_char=0,
        local_end_char=2,
        global_start_char=0,
        global_end_char=2,
        matched_keywords=("词",),
        match_count=1,
    )

    assert row.matched_keywords == ("词",)
