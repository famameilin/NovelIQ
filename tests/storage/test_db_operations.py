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
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.agents.diagnosis.persistence import save_diagnosis_report
from src.diagnosis.read import fetch_diagnosis_payload
from src.diagnosis.schema import AgentAnalysis
from src.storage.repositories import (
    ChapterRepository,
    ParagraphRepository,
    RunRepository,
    StatsRepository,
)
from src.text_processing.paragraphs import chunk_text, split_chunk_paragraphs
from tests.support.analysis_factories import insert_test_novel
from tests.support.chapter_annotation_helpers import character_fact, persist_chapter_annotation
from tests.support.event_tree_fixtures import add_diagnosis_context, ensure_character


def test_create_and_insert(db_session) -> None:
    text_content = "\n\n".join(["a" * 600] * 2)
    chunks = asyncio.run(chunk_text(text_content))

    novel_id = uuid.uuid4().hex[:8]
    insert_test_novel(novel_id, session=db_session)
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id=novel_id, source_path="test", title="Test Novel")

    chapter_repo = ChapterRepository(db_session)

    chapter_repo.insert_chapter_texts(run_id, chunks)
    # 2026-08-18 段落事实源：证据派生要求章节存在段落行
    spans = [replace(span, token_count=1) for span in split_chunk_paragraphs(chunks)]
    ParagraphRepository(db_session).insert_paragraphs(run_id, spans)
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[
            character_fact(
                chapter_id=chunks[0].chapter_id,
                name="张三",
                action="走",
            )
        ],
    )
    rows = chapter_repo.fetch_chapter_texts(run_id)
    assert len(rows) == len(chunks)
    assert rows[0][0] == 1
    # 2026-10-16 3NF：正文终点不是章节列，读面按 char_offset + 字符长度投影
    bodies = {row.chapter_id: row for row in chapter_repo.fetch_chapter_bodies(run_id)}
    assert bodies[1].char_offset == chunks[0].start
    assert bodies[1].char_end_offset == chunks[0].end


def test_insert_chapter_texts_keeps_duplicate_chapter_titles_separate(db_session) -> None:
    """
    2026-08-02 用于保证重复章节标题按出现序号落为不同 chapter_id
    """
    text_content = "第1章 序章\n甲。\n第2章 中段\n乙。\n第1章 序章\n丙。"
    chunks = asyncio.run(chunk_text(text_content))

    novel_id = uuid.uuid4().hex[:8]
    insert_test_novel(novel_id, session=db_session)
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id,
        source_path="test",
        title="Duplicate Chapter Titles",
    )

    chapter_repo = ChapterRepository(db_session)
    chapter_repo.insert_chapter_texts(run_id, chunks)
    rows = chapter_repo.fetch_chapter_texts(run_id)

    assert [row[0] for row in rows] == [1, 2, 3]


def test_get_run_by_run_id_prefix_escapes_like_wildcards(db_session) -> None:
    """
    2026-08-13 P2-9 用于验证 run_id 前缀查询对 % 与 _ 做字面转义，
    前缀里的通配符不再误匹配其他 run。
    """
    novel_id = uuid.uuid4().hex[:8]
    insert_test_novel(novel_id, session=db_session)
    run_repo = RunRepository(db_session)
    run_repo.create_run(novel_id=novel_id, source_path="test", title="A", run_id="pre_1%fix")
    run_repo.create_run(novel_id=novel_id, source_path="test", title="B", run_id="pre_1Xfix")
    run_repo.create_run(novel_id=novel_id, source_path="test", title="C", run_id="pre_2Xfix")
    db_session.commit()

    # 前缀含 %：未转义时 pre_1%fix% 会通配匹配 pre_1Xfix，转义后只命中字面 run
    assert run_repo.get_run_by_run_id_prefix("pre_1%fix")["run_id"] == "pre_1%fix"
    # 前缀含 _：未转义时 pre_1X% 会通配匹配 pre_2Xfix，转义后只命中字面 run
    assert run_repo.get_run_by_run_id_prefix("pre_1X")["run_id"] == "pre_1Xfix"
    assert run_repo.get_run_by_run_id_prefix("pre_2X")["run_id"] == "pre_2Xfix"


def test_retired_analysis_output_entrypoints_raise(db_session) -> None:
    """2026-10-16 3NF：旧通用分析产物入口已退役，诊断报告只走 diagnosis_reports 正式关系"""
    novel_id = uuid.uuid4().hex[:8]
    insert_test_novel(novel_id, session=db_session)
    run_id = RunRepository(db_session).create_run(novel_id=novel_id, source_path="test", title="Test Novel")
    stats_repo = StatsRepository(db_session)

    with pytest.raises(NotImplementedError):
        stats_repo.insert_agent_analysis(run_id, {"novel_id": novel_id})
    with pytest.raises(NotImplementedError):
        stats_repo.fetch_agent_analysis(run_id)


def test_insert_agent_analysis(db_session) -> None:
    """2026-10-16 3NF：正式诊断经 diagnosis_reports 保存，按正式读接口取回"""
    novel_id = uuid.uuid4().hex[:8]
    insert_test_novel(novel_id, session=db_session)
    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id=novel_id, source_path="test", title="Test Novel")
    for name in ("角色0", "角色1"):
        ensure_character(db_session, run_id=run_id, name=name)

    session_id, _work_id, _execution_id = add_diagnosis_context(db_session, run_id)
    save_diagnosis_report(
        db_session,
        run_id,
        session_id,
        AgentAnalysis(
            novel_id=novel_id,
            arc_scores={"角色0": 8.2, "角色1": 7.4},
            diagnosis="ok",
            narrative_arc_type="白手起家",
            focus_structure="dual",
            focus_characters=["角色0", "角色1"],
            main_characters=["角色0", "角色1"],
            core_cast=["角色0", "角色1"],
        ),
    )
    db_session.commit()

    fetched = fetch_diagnosis_payload(db_session, run_id)
    assert fetched is not None
    assert fetched["novel_id"] == novel_id
    assert fetched["narrative_arc_type"] == "白手起家"
    assert fetched["focus_structure"] == "dual"
    assert fetched["arc_scores"] == {"角色0": 8.2, "角色1": 7.4}


def test_fetch_agent_analysis_prefers_latest_row_for_same_run(db_session) -> None:
    """2026-10-16 3NF：同一 run 至多一份正式诊断发布（第二次发布被领域约束拒绝）"""
    novel_id = uuid.uuid4().hex[:8]
    insert_test_novel(novel_id, session=db_session)

    run_repo = RunRepository(db_session)
    run_id = run_repo.create_run(novel_id=novel_id, source_path="test", title="Test Novel")
    ensure_character(db_session, run_id=run_id, name="角色0")

    session_id, _work_id, _execution_id = add_diagnosis_context(db_session, run_id)
    save_diagnosis_report(
        db_session,
        run_id,
        session_id,
        AgentAnalysis(
            novel_id=novel_id,
            diagnosis="first",
            focus_structure="single",
            focus_characters=["角色0"],
            main_characters=["角色0"],
            core_cast=["角色0"],
        ),
    )
    db_session.commit()

    second_session_id, _work_id2, _execution_id2 = add_diagnosis_context(db_session, run_id)
    with pytest.raises(IntegrityError):
        save_diagnosis_report(
            db_session,
            run_id,
            second_session_id,
            AgentAnalysis(novel_id=novel_id, diagnosis="second"),
        )
        # 唯一性由领域约束在提交时校验，第二次发布不得覆盖已发布报告
        db_session.commit()
    db_session.rollback()

    fetched = fetch_diagnosis_payload(db_session, run_id)
    assert fetched is not None
    assert fetched["focus_structure"] == "single"
