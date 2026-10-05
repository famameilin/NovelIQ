"""正式章节独立提交、未来原文来源和不可变冲突"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.agents.annotation.identity import stable_digest, stable_uuid, text_digest
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    ChapterMetricsInput,
    SourceReference,
)
from src.storage.db import get_session_factory
from src.storage.models import (
    AnalysisRun,
    Chapter,
    ChapterAnnotationRecord,
    Novel,
    Paragraph,
    SemanticCommand,
    SourceManifest,
    TextEvidenceRecord,
)
from src.storage.repositories.formal_chapter import FormalChapterRepository
from src.storage.repositories.pipeline_resolution import bind_record_target
from src.storage.repositories.pipeline_source import formal_receipt
from src.storage.repositories.pipeline_work import ImmutableWorkConflict, WorkReceipt

pytestmark = pytest.mark.usefixtures("pipeline_run_cleanup")


def _source() -> tuple[str, WorkReceipt]:
    run_id = str(uuid4())
    source_hash = stable_digest(run_id, "source-manifest")
    novel_id = uuid4().hex[:8]
    with get_session_factory()() as session, session.begin():
        session.add(Novel(novel_id=novel_id, title="正式结果测试"))
        session.flush()
        session.add(AnalysisRun(run_id=run_id, novel_id=novel_id, status="running"))
        session.flush()
        for chapter_id, text in ((1, "第一章原文"), (2, "未来章节原文")):
            session.add(
                Chapter(
                    chapter_id=chapter_id,
                    run_id=run_id,
                    sequence=chapter_id,
                    title=f"第{chapter_id}章",
                    display_title=f"第{chapter_id}章",
                    level="chapter",
                    start_pos=0,
                    end_pos=len(text),
                    text=text,
                    char_offset=0,
                    char_end_offset=len(text),
                )
            )
            session.flush()
            session.add(
                Paragraph(
                    run_id=run_id,
                    paragraph_id=chapter_id,
                    chapter_id=chapter_id,
                    paragraph_index=0,
                    source_paragraph_index=0,
                    fragment_index=0,
                    local_start_char=0,
                    local_end_char=len(text),
                    global_start_char=chapter_id * 100,
                    global_end_char=chapter_id * 100 + len(text),
                    char_count=len(text),
                    token_count=4,
                    text=text,
                )
            )
    with get_session_factory()() as session, session.begin():
        session.add(
            SourceManifest(
                source_manifest_hash=source_hash,
                run_id=run_id,
                chapter_hashes={"1": text_digest("第一章原文"), "2": text_digest("未来章节原文")},
                paragraph_hashes={"1": text_digest("第一章原文"), "2": text_digest("未来章节原文")},
            )
        )
    text = "第一章原文"
    receipt = formal_receipt(run_id, {
        "chapter_id": 1,
        "chapter_sequence": 1,
        "source_manifest_hash": source_hash,
        "chapter_text_hash": text_digest(text),
        "paragraph_manifest_hash": stable_digest([(1, 0, len(text), text_digest(text))]),
    })
    return run_id, receipt


def _result(run_id: str, *, summary: str = "本章摘要") -> AgentRunResult:
    return AgentRunResult(
        run_id=run_id,
        chapter_id=1,
        annotation=BoundChapterAnnotation(
            metrics=ChapterMetricsInput(summary=summary, emotional_valence=0, narrative_function="铺垫"),
            character_observations=[],
            dialogues=[],
            events=[],
        ),
        entity_ops=[
            {
                "name": "甲",
                "entity_type": "character",
                "tags": [],
                "description": None,
                "attributes": {},
                "chapter_id": 1,
            }
        ],
        audit=AgentRunAudit(
            allow_future_context=True,
            write_records=[],
            authorized_text_paragraph_ids=[2],
        ),
    )


def test_formal_commit_records_future_source_and_projection_work() -> None:
    run_id, receipt = _source()
    annotation_id = FormalChapterRepository(get_session_factory()).commit(receipt, _result(run_id))
    with get_session_factory()() as session:
        row = session.get(ChapterAnnotationRecord, annotation_id)
        assert row is not None
        assert row.formal_work_id == receipt.work_id
        assert row.payload_hash is not None
        assert (
            session.execute(
                select(func.count()).select_from(TextEvidenceRecord).where(TextEvidenceRecord.run_id == run_id)
            ).scalar_one()
            == 2
        )
        commands = list(session.execute(select(SemanticCommand).where(SemanticCommand.run_id == run_id)).scalars())
        assert len(commands) == 2
        assert all(len(command.evidence_ids) == 2 for command in commands)


def test_formal_commit_rejects_changed_source_without_partial_write() -> None:
    run_id, receipt = _source()
    with get_session_factory()() as session, session.begin():
        chapter = session.get(Chapter, (1, run_id))
        assert chapter is not None
        chapter.text = "来源已经改变"
    with pytest.raises(ImmutableWorkConflict):
        FormalChapterRepository(get_session_factory()).commit(receipt, _result(run_id))
    with get_session_factory()() as session:
        assert (
            session.execute(
                select(func.count())
                .select_from(ChapterAnnotationRecord)
                .where(ChapterAnnotationRecord.run_id == run_id)
            ).scalar_one()
            == 0
        )


def test_formal_commit_redelivery_is_idempotent_and_conflicts_on_changed_payload() -> None:
    """重启恢复的幂等底线：同一回执重提交返回既有结果；载荷变化必须炸出来"""
    run_id, receipt = _source()
    repository = FormalChapterRepository(get_session_factory())
    annotation_id = repository.commit(receipt, _result(run_id))
    assert repository.commit(receipt, _result(run_id)) == annotation_id
    with pytest.raises(ImmutableWorkConflict):
        repository.commit(receipt, _result(run_id, summary="另一份载荷"))


def test_bind_record_target_tolerates_not_dialogue_candidate() -> None:
    """2026-10-03 对话候选被判 not_dialogue 时案例锚点降级为无域绑定，不炸整章

    候选被模型或收尾兜底判成 not_dialogue 后就从正式对话产出里消失——案例在判定前
    push，锚点在提交期失配是合法时序（run 4a6c268c ch17 的整章失败）。案例保留原
    record_id 便于追溯，只是拿不到对话域绑定（说话人订正自然不可用）。
    """
    result = _result(str(uuid4()))
    assert bind_record_target("dialogue/15", result) == {}
    assert bind_record_target("dialogue/not-a-candidate", result) == {}


def test_formal_commit_skips_anchor_on_vanished_not_dialogue_candidate() -> None:
    """2026-10-03 已消失对话候选的锚点不落 object_anchor（run 08f9ba42 收官 KeyError('domain')）

    ch11/ch25 曾把 not_dialogue 消失候选的锚点写成 object: {} 落库，聚合期
    resolve_cross_chapter_links 取 payload["object"]["domain"] 时 KeyError 炸全 run。
    正式产出的锚点（entity/甲）必须照常落库。
    """
    run_id, receipt = _source()
    result = _result(run_id)
    anchor = SourceReference(
        chapter_id=1,
        paragraph_id=1,
        char_start=0,
        char_end=2,
        text_hash=text_digest("第一"),
    )
    result.audit.source_anchors = {
        "dialogue/15": [anchor],
        "entity/甲": [anchor],
    }
    FormalChapterRepository(get_session_factory()).commit(receipt, result)
    with get_session_factory()() as session:
        anchors = list(
            session.execute(
                select(SemanticCommand).where(
                    SemanticCommand.run_id == run_id,
                    SemanticCommand.command_kind == "object_anchor",
                )
            ).scalars()
        )
        assert len(anchors) == 1
        assert anchors[0].payload["object"]["domain"] == "entity"
        assert anchors[0].payload["object"]["entity_id"]


def test_bind_record_target_binds_production_keys() -> None:
    """2026-10-03 生产键（实体/对话/事件）照常绑定确切目标"""
    run_id = str(uuid4())
    result = _result(run_id)
    result.annotation.dialogues = [
        SimpleNamespace(candidate_key="dlg_abc", candidate_index=15),
    ]
    event_id = stable_uuid(run_id, 1, "event_node", "t1", "root")
    result.annotation.events = [SimpleNamespace(node_id=event_id)]
    assert bind_record_target("dialogue/15", result) == {"domain": "dialogue", "candidate_key": "dlg_abc"}
    assert bind_record_target("entity/甲", result)["domain"] == "entity"
    assert bind_record_target("t1/root", result) == {"domain": "event", "event_id": event_id}
    with pytest.raises(ValueError, match="事件不是本章正式产出"):
        bind_record_target("t1/e404", result)
