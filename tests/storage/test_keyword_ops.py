"""关键词检索测试：直接扫 paragraphs 事实源 + trgm 索引

keyword_ops.search_paragraphs_by_keywords 不再扫 chunks + Python 重切段，
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.storage import new_id
from src.storage.repositories.paragraph.keyword_ops import (
    fetch_chunk_text,
    search_paragraphs_by_keywords,
)
from tests.support.storage_fixtures import fixture_id


def test_search_paragraphs_by_keywords_orders_by_match_count() -> None:
    """SQL 直接扫 paragraphs 行，按 (-match_count, paragraph_id) 排序"""
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            paragraph_id=4,
            chapter_id=3,
            paragraph_index=1,
            text="赤羽炽尾鸡被阵法镇压，猴子去拔尾羽。",
            local_start_char=0,
            local_end_char=15,
            global_start_char=100,
            global_end_char=115,
        ),
        SimpleNamespace(
            paragraph_id=1,
            chapter_id=1,
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
        run_id=fixture_id(__name__, "run-1"),
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
    """过滤数据库替身返回的非字面命中段落"""
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            paragraph_id=2,
            chapter_id=2,
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
        run_id=fixture_id(__name__, "run-1"),
        keywords=["不存在词"],
        top_k=5,
    )

    assert results == []


def test_search_paragraphs_by_keywords_rejects_empty_keywords() -> None:
    """拒绝空关键词请求且不访问数据库"""
    session = MagicMock()

    results = search_paragraphs_by_keywords(session, run_id=fixture_id(__name__, "run-1"), keywords=["  ", ""], top_k=5)

    assert results == []
    session.execute.assert_not_called()


def test_search_paragraphs_by_keywords_scans_paragraphs_table() -> None:
    """查询 FROM paragraphs（不再 FROM chunks），
    命中条件为 lower(text) LIKE（trgm 可命中 lower(text) gin_trgm_ops 索引）
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            paragraph_id=3,
            chapter_id=0,
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
        run_id=fixture_id(__name__, "run-1"),
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


def test_search_paragraphs_by_keywords_treats_wildcards_as_globs_and_deduplicates() -> None:
    """保证 %/_ 按 LIKE 通配符语义匹配（不再转义为字面量）
    且重复关键词不重复计分
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            paragraph_id=2,
            chapter_id=2,
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
        run_id=fixture_id(__name__, "run-1"),
        keywords=["100%", "A_B", "100%"],
        top_k=5,
    )

    stmt = session.execute.call_args.args[0]
    compiled_sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "ESCAPE" not in compiled_sql
    assert len(results) == 1
    # 词项统一小写归一后 matched_keywords 保留小写形式
    # 100% → 前缀通配命中"100"；A_B → A+任意单字符+B 命中"A_B"
    assert results[0].matched_keywords == ("100%", "a_b")
    assert results[0].match_count == 2


def test_search_paragraphs_by_keywords_matches_case_insensitively() -> None:
    """验证查询词项（已小写）能命中大小写混合的原文，
    SQL LIKE 与 Python 侧子串匹配都做 lower 归一，英文词不再因大小写漏命中。
    """
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        SimpleNamespace(
            paragraph_id=2,
            chapter_id=2,
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
        run_id=fixture_id(__name__, "run-1"),
        keywords=["sword"],
        top_k=5,
    )

    stmt = session.execute.call_args.args[0]
    compiled_sql = str(stmt.compile())
    assert "lower(paragraphs.text) LIKE" in compiled_sql
    assert len(results) == 1
    assert results[0].matched_keywords == ("sword",)
    assert results[0].match_count == 1


def test_fetch_chunk_text_returns_text_when_missing_returns_none(db_session) -> None:
    """关键词检索的 local/global 坐标由 chapters.char_offset
    与段落正文长度投影得到，章节正文读取 chapters.text（正文与目录同键一行）
    """
    from dataclasses import replace

    from src.storage.repositories import ChapterRepository, RunRepository
    from src.storage.repositories.paragraph_repository import ParagraphRepository
    from src.text_processing.models import Chunk
    from src.text_processing.paragraphs import split_chunk_paragraphs
    from src.text_processing.tokenize import tokenize
    from tests.support.analysis_factories import insert_test_novel

    novel_id = new_id()
    insert_test_novel(novel_id, session=db_session)
    run_id = RunRepository(db_session).create_run(novel_id=novel_id)
    chunk_text = "灰衣人站在门外。\n屋内传来声响。\n"
    ChapterRepository(db_session).insert_chapter_texts(
        run_id,
        [Chunk(index=0, text=chunk_text, start=100, end=100 + len(chunk_text), chapter_id=1)],
    )
    spans = split_chunk_paragraphs(
        [Chunk(index=0, text=chunk_text, start=100, end=100 + len(chunk_text), chapter_id=1)]
    )
    spans = [replace(span, token_count=len(tokenize(span.text))) for span in spans]
    ParagraphRepository(db_session).insert_paragraphs(run_id, spans)
    db_session.commit()

    results = search_paragraphs_by_keywords(db_session, run_id=run_id, keywords=["灰衣人"], top_k=5)
    assert len(results) == 1
    hit = results[0]
    assert hit.paragraph_text == "灰衣人站在门外。"
    assert (hit.local_start_char, hit.local_end_char) == (0, len("灰衣人站在门外。"))
    assert hit.global_start_char == 100 + hit.local_start_char
    assert hit.global_end_char == 100 + hit.local_end_char

    assert fetch_chunk_text(db_session, run_id=run_id, chapter_id=1) == chunk_text
    assert fetch_chunk_text(db_session, run_id=run_id, chapter_id=99) is None


def test_fetch_chunk_text_returns_text_when_present() -> None:
    """返回存在的历史 chunk 原文"""
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = "完整章节原文。"

    text = fetch_chunk_text(session, run_id=fixture_id(__name__, "run-1"), chapter_id=3)

    assert text == "完整章节原文。"


def test_fetch_chunk_text_returns_none_when_missing() -> None:
    """在历史 chunk 不存在时返回 None"""
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    text = fetch_chunk_text(session, run_id=fixture_id(__name__, "run-1"), chapter_id=99)

    assert text is None
