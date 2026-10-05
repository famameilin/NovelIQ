"""章节序工作合同：回执确定性、完成差集与按序恢复"""

from __future__ import annotations

import pytest

from src.agents.annotation.schema import BoundChapterAnnotation, ChapterMetricsInput
from src.storage.db import get_session_factory
from src.storage.repositories.pipeline_source import (
    formal_committed_chapter_ids,
    formal_receipt,
    prepare_formal_work,
)
from tests.support.chapter_annotation_helpers import commit_test_annotation, create_run_with_chunks

pytestmark = pytest.mark.usefixtures("pipeline_run_cleanup")


def _annotation(summary: str) -> BoundChapterAnnotation:
    return BoundChapterAnnotation(
        metrics=ChapterMetricsInput(summary=summary, emotional_valence=0, narrative_function="铺垫"),
        character_observations=[],
        dialogues=[],
        events=[],
    )


def test_prepare_formal_work_lists_chapters_in_sequence_order_with_stable_identity(db_session) -> None:
    """任务列表 = 按章节序读库；work_id 由 run+章节+载荷+快照确定性铸出，重跑不变"""
    _, run_id = create_run_with_chunks(db_session, texts=["第一章", "第二章", "第三章"], chapter_ids=[3, 1, 2])
    db_session.commit()
    factory = get_session_factory()

    first = prepare_formal_work(factory, run_id)
    second = prepare_formal_work(factory, run_id)
    assert [receipt.payload["chapter_id"] for receipt in first] == [1, 2, 3]
    assert [receipt.payload["chapter_sequence"] for receipt in first] == [1, 2, 3]
    assert [receipt.work_id for receipt in first] == [receipt.work_id for receipt in second]
    for receipt in first:
        assert formal_receipt(run_id, receipt.payload).work_id == receipt.work_id
        assert receipt.cutoff_hash == receipt.payload["source_manifest_hash"]


def test_formal_committed_chapter_ids_tracks_committed_annotations(db_session) -> None:
    """章节状态即工作状态：有正式标注 = 已完成，恢复 = 重查后按差集补跑"""
    _, run_id = create_run_with_chunks(db_session, texts=["第一章", "第二章"], chapter_ids=[1, 2])
    db_session.commit()
    factory = get_session_factory()

    assert formal_committed_chapter_ids(factory, run_id) == set()
    work = prepare_formal_work(factory, run_id)
    commit_test_annotation(db_session, run_id=run_id, chapter_id=1, annotation=_annotation("第一章"))
    assert formal_committed_chapter_ids(factory, run_id) == {1}

    resumed = prepare_formal_work(factory, run_id)
    pending = [item for item in resumed if item.payload["chapter_id"] not in {1}]
    assert [item.payload["chapter_id"] for item in pending] == [2]
    assert {item.payload["chapter_id"]: item.work_id for item in resumed} == {
        item.payload["chapter_id"]: item.work_id for item in work
    }
