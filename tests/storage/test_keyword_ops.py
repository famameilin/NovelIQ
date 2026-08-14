"""
二期段落化关键词检索测试：直接扫 paragraphs 事实源 + trgm 索引

创建时间: 2026-08-14
任务: M5 检索段落化（§12.1）
说明: keyword_ops.search_paragraphs_by_keywords 不再扫 chunks + Python 重切段，
段落身份与 local/global 坐标一律取 paragraphs 持久化列。
"""

import re
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy import text

from src.storage.repositories.chunk.keyword_ops import (
    KeywordMatchRow,
    fetch_chunk_text,
    search_paragraphs_by_keywords,
)


def test_search_paragraphs_by_keywords_orders_by_match_count() -> None:
    """
    2026-08-14 二期段落化：SQL 直接扫 paragraphs 行，按 (-match_count, paragraph_id) 排序
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            paragraph_id=4,
            chunk_id=3,
            paragraph_index=1,
            text="赤羽炽尾鸡被阵法镇压，猴子去拔尾羽。",
            local_start_char=0,
            local_end_char=15,
            global_start_char=100,
            global_end_char=115,
        ),
        SimpleNamespace(
            paragraph_id=1,
            chunk_id=1,
            paragraph_index=0,
            text="赤羽炽尾鸡是灵兽。",
            local_start_char=0,
            local_end_char=8,
            global_start_char=10,
            global_end_char=18,
        ),
    ]

    results = search_paragraphs_by_keywords(
        session,
        run_id="run-1",
        keywords=["赤羽炽尾鸡", "阵法", "猴子"],
        top_k=5,
    )

    assert [r.paragraph_id for r in results] == [4, 1]
    assert results[0].match_count == 3
    assert results[0].matched_keywords == ("赤羽炽尾鸡", "阵法", "猴子")
    assert results[0].global_start_char == 100
    # 坐标直接取 paragraphs 持久化列，不再回退累计偏移
    assert results[0].local_start_char == 0
    assert results[0].local_end_char == 15


def test_search_paragraphs_by_keywords_filters_non_matching_rows() -> None:
    """
    2026-08-02 用于过滤数据库替身返回的非字面命中段落
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            paragraph_id=2,
            chunk_id=2,
            paragraph_index=0,
            text="普通段落没有命中词。",
            local_start_char=0,
            local_end_char=9,
            global_start_char=50,
            global_end_char=59,
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


def test_search_paragraphs_by_keywords_scans_paragraphs_table() -> None:
    """
    2026-08-14 二期段落化：查询 FROM paragraphs（不再 FROM chunks），
    命中条件为 lower(text) LIKE（trgm 可命中 lower(text) gin_trgm_ops 索引）
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            paragraph_id=3,
            chunk_id=0,
            paragraph_index=0,
            text="顾霜入城。",
            local_start_char=0,
            local_end_char=5,
            global_start_char=0,
            global_end_char=5,
        ),
    ]

    results = search_paragraphs_by_keywords(
        session,
        run_id="run-1",
        keywords=["叶文洁", "顾霜"],
        top_k=3,
    )

    stmt = session.execute.call_args.args[0]
    compiled_sql = str(stmt.compile())
    assert "FROM paragraphs" in compiled_sql
    assert "FROM chunks" not in compiled_sql
    assert compiled_sql.count("LIKE") == 2
    assert len(results) == 1
    assert results[0].paragraph_id == 3
    assert results[0].matched_keywords == ("顾霜",)
    assert results[0].match_count == 1


def test_search_paragraphs_by_keywords_pushes_paragraph_bounds_into_sql() -> None:
    """
    2026-08-14 二期段落化：exclude/min/max 边界全部改为 paragraph_id 并进入 SQL
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = []

    search_paragraphs_by_keywords(
        session,
        run_id="run-1",
        keywords=["叶文洁"],
        top_k=3,
        exclude_paragraph_ids=[5],
        min_paragraph_id=1,
        max_paragraph_id=10,
    )

    stmt = session.execute.call_args.args[0]
    compiled_sql = str(stmt.compile())
    assert "paragraph_id NOT IN" in compiled_sql
    assert re.search(r"paragraph_id >= :paragraph_id_\d+", compiled_sql) is not None
    assert re.search(r"paragraph_id <= :paragraph_id_\d+", compiled_sql) is not None


def test_search_paragraphs_by_keywords_escapes_sql_wildcards_and_deduplicates() -> None:
    """
    2026-08-02 用于保证百分号下划线按字面子串匹配且重复关键词不重复计分
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            paragraph_id=2,
            chunk_id=2,
            paragraph_index=0,
            text="完成度达到100%，代号为A_B。",
            local_start_char=0,
            local_end_char=16,
            global_start_char=50,
            global_end_char=66,
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


def test_search_paragraphs_by_keywords_matches_case_insensitively() -> None:
    """
    2026-08-13 P2-6 用于验证查询词项（已小写）能命中大小写混合的原文，
    SQL LIKE 与 Python 侧子串匹配都做 lower 归一，英文词不再因大小写漏命中。
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            paragraph_id=2,
            chunk_id=2,
            paragraph_index=0,
            text="顾霜持 Sword 现身，Sword 寒光凛冽。",
            local_start_char=0,
            local_end_char=19,
            global_start_char=50,
            global_end_char=69,
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
    assert "lower(paragraphs.text) LIKE" in compiled_sql
    assert len(results) == 1
    assert results[0].matched_keywords == ("sword",)
    assert results[0].match_count == 1


def test_keyword_match_row_is_frozen_dataclass() -> None:
    """
    2026-08-02 用于锁定关键词命中 DTO 的不可变结构（二期新增 paragraph_id）
    """
    row = KeywordMatchRow(
        paragraph_id=3,
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

    assert row.paragraph_id == 3
    assert row.matched_keywords == ("词",)


def test_paragraphs_table_has_lower_text_trgm_index(db_session) -> None:
    """
    2026-08-14 二期段落化（§12.1）：keyword_ops 直接扫 paragraphs.text，
    paragraphs 表必须建 lower(text) gin_trgm_ops 的 GIN 索引（与 chunks 同口径）。
    """
    runtime_schema = db_session.execute(text("SELECT current_schema()")).scalar_one()
    indexdef = db_session.execute(
        text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = :schema_name
              AND tablename = 'paragraphs'
              AND indexname = 'idx_paragraphs_text_trgm'
            """
        ),
        {"schema_name": runtime_schema},
    ).scalar_one_or_none()
    assert indexdef is not None
    assert "USING gin" in indexdef
    assert "lower(text) gin_trgm_ops" in indexdef


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
