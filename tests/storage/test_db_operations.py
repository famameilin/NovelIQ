"""
测试数据库操作

修改时间: 2026-03-15
任务: storage-layer-decoupling
修改内容: 使用 SessionFactory 替代 connect_db/create_tables，确保正确关闭连接

修改时间: 2026-03-15
任务: postgresql-migration
修改内容: 使用 SQLAlchemy text() 替换 ? 占位符，移除 sqlite3 导入，添加 analysis_runs 记录创建

修改时间: 2026-03-15
任务: 配置独立测试数据库
修改内容: 改用 pytest 风格，使用 db_session fixture

修改时间: 2026-03-15
任务: postgresql-migration-cleanup
修改内容: 重命名测试文件，移除 sqlite 相关命名

修改时间: 2026-04-09
任务: async-reconstruction
修改内容: chunk_text 改为 async，添加 asyncio.run() 包装
"""

import asyncio
import sys
import uuid
from pathlib import Path

from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import chunk_text
from src.models.cloud.schema import CloudAnalysis
from src.storage.models import Novel
from src.storage.repositories import (
    ChunkRepository,
    ChunkStyleData,
    RunRepository,
    StatsRepository,
)
from tests.support.chapter_annotation_helpers import character_fact, persist_chapter_annotation


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


def test_create_and_insert(db_session) -> None:
    text_content = "\n\n".join(["a" * 600] * 2)
    chunks = asyncio.run(chunk_text(text_content, max_chars=1000, split_by_chapter=False))

    novel_id = uuid.uuid4().hex[:8]
    _insert_test_novel(db_session, novel_id)
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id=novel_id, source_path="test", title="Test Novel")

    chunk_repo = ChunkRepository(db_session)

    chunk_repo.insert_chunks(run_id, chunks)
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(
                chunk_id=chunks[0].index,
                name="张三",
                action="走",
            )
        ],
    )
    chunk_repo.insert_chunk_style(
        run_id,
        [
            ChunkStyleData(
                chunk_id=chunks[0].index,
                mtld=1.0,
                ttr=0.5,
                avg_sent_len=12.0,
                sent_len_std=3.0,
                d_value=0.8,
                pause_density=0.2,
                fight_density=0.1,
                exclaim_density=0.05,
                dialogue_ratio=0.3,
                question_density=0.02,
                sensory_density=0.04,
                metaphor_density=0.01,
                function_word_vector="{}",
                category_density_combat=0.0,
                category_density_body=0.0,
                category_density_relation=0.0,
                category_density_faction=0.0,
                category_density_command=0.0,
                category_density_action=0.0,
                category_density_psychology=0.0,
                category_density_measure=0.0,
                category_density_emotion=0.0,
                category_density_color=0.0,
            )
        ],
    )
    rows = chunk_repo.fetch_chunk_texts(run_id)
    assert len(rows) == len(chunks)
    assert rows[0][0] == 0
    offset_row = db_session.execute(
        text("SELECT char_offset, char_end_offset FROM chunks WHERE run_id = :run_id AND chunk_id = 0"),
        {"run_id": run_id},
    ).fetchone()
    assert offset_row is not None
    assert offset_row.char_offset == chunks[0].start
    assert offset_row.char_end_offset == chunks[0].end


def test_insert_chunks_keeps_duplicate_chapter_titles_separate(db_session) -> None:
    """
    2026-08-02 用于保证重复章节标题按出现序号落为不同 chapter_id
    """
    text_content = "第1章 序章\n甲。\n第2章 中段\n乙。\n第1章 序章\n丙。"
    chunks = asyncio.run(chunk_text(text_content, max_chars=100, overlap=0, split_by_chapter=True))

    novel_id = uuid.uuid4().hex[:8]
    _insert_test_novel(db_session, novel_id)
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Duplicate Chapter Titles",
    )

    chunk_repo = ChunkRepository(db_session)
    chunk_repo.insert_chunks(run_id, chunks)
    rows = chunk_repo.fetch_chunks_with_chapter(run_id)

    assert [row[1] for row in rows] == [1, 2, 3]


def test_insert_cloud_analysis(db_session) -> None:
    novel_id = uuid.uuid4().hex[:8]
    _insert_test_novel(db_session, novel_id)
    analysis = CloudAnalysis(
        novel_id=novel_id,
        foreshadow_expectation=0.5,
        arc_scores={"角色0": 8.2, "角色1": 7.4},
        genre_labels=["通用"],
        style_labels=["严肃"],
        topic_labels=["成长"],
        diagnosis="ok",
        narrative_arc_type="白手起家",
        focus_structure="dual",
        focus_characters=["角色0", "角色1"],
        main_characters=["角色0", "角色1"],
        core_cast=["角色0", "角色1"],
    )

    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id=novel_id, source_path="test", title="Test Novel")

    stats_repo = StatsRepository(db_session)
    stats_repo.insert_cloud_analysis(run_id, analysis)
    row = db_session.execute(
        text("SELECT novel_id, foreshadow_expectation, narrative_arc_type FROM cloud_analysis WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).fetchone()
    assert row[0] == novel_id
    assert row[1] == 0.5
    assert row[2] == "白手起家"


def test_fetch_cloud_analysis_prefers_latest_row_for_same_run(db_session) -> None:
    novel_id = uuid.uuid4().hex[:8]
    _insert_test_novel(db_session, novel_id)

    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id=novel_id, source_path="test", title="Test Novel")

    stats_repo = StatsRepository(db_session)
    stats_repo.insert_cloud_analysis(
        run_id,
        CloudAnalysis(
            novel_id=novel_id,
            foreshadow_expectation=0.2,
            arc_scores={"角色0": 7.0},
            genre_labels=["通用"],
            style_labels=["严肃"],
            topic_labels=["旧主题"],
            diagnosis="old",
            narrative_arc_type="白手起家",
            focus_structure="single",
            focus_characters=["角色0"],
            main_characters=["角色0"],
            core_cast=["角色0"],
        ),
    )
    stats_repo.insert_cloud_analysis(
        run_id,
        CloudAnalysis(
            novel_id=novel_id,
            foreshadow_expectation=0.8,
            arc_scores={"角色1": 9.0},
            genre_labels=["科幻"],
            style_labels=["硬核"],
            topic_labels=["新主题"],
            diagnosis="new",
            narrative_arc_type="白手起家",
            focus_structure="single",
            focus_characters=["角色1"],
            main_characters=["角色1"],
            core_cast=["角色1"],
        ),
    )

    fetched = stats_repo.fetch_cloud_analysis(novel_id, run_id)

    assert fetched is not None
    assert fetched["genre_labels"] == '["科幻"]'
    assert fetched["style_labels"] == '["硬核"]'
    assert fetched["foreshadow_expectation"] == 0.8
