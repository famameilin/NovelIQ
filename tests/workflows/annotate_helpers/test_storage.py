"""章节标注原子完成事务测试"""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.agents.annotation.candidates import extract_dialogue_candidates
from src.agents.annotation.schema import (
    AgentRunAudit,
    AgentRunResult,
    BoundChapterAnnotation,
    BoundChunkAnnotation,
    BoundDialogue,
    ChunkMetricsInput,
    PendingCase,
    ResolvedCase,
)
from src.storage.models import (
    CasePoolCase,
    CaseResolutionMapping,
    ChapterAnnotationRecord,
    DialogueRecord,
)
from src.workflows.annotate_helpers.storage import (
    _fold_resolved_cases,
    complete_annotation_run,
    load_completion_result,
)
from tests.support.chapter_annotation_helpers import create_run_with_chunks


def _annotation(
    *,
    chunk_id: int,
    text: str,
    unresolved_dialogue: bool = False,
) -> BoundChapterAnnotation:
    """2026-08-07 用于构造含未解决对话的系统绑定章节标注"""
    dialogues: list[BoundDialogue] = []
    if unresolved_dialogue:
        candidate = next(item for item in extract_dialogue_candidates(chunk_id, text) if item.content == "住手")
        dialogues.append(
            BoundDialogue(
                candidate_index=1,
                candidate_key=candidate.candidate_key,
                content=candidate.content,
                start=candidate.start,
                end=candidate.end,
                speaker=None,
                tone="紧张",
                is_inner_monologue=False,
            )
        )
    return BoundChapterAnnotation(
        chapter_summary=text,
        chunks=[
            BoundChunkAnnotation(
                chunk_id=chunk_id,
                metrics=ChunkMetricsInput(
                    summary=text,
                    emotional_valence=0,
                    narrative_function="铺垫",
                ),
                character_observations=[],
                dialogues=dialogues,
                events=[],
            )
        ],
    )


def _audit(
    *,
    authorized_chunk_ids: list[int],
) -> AgentRunAudit:
    """2026-08-10 用于构造完成事务审计（完整工具审计由 AgentAuditRecorder 独立写入）"""
    return AgentRunAudit(
        allow_future_context=False,
        write_records=[],
        authorized_chapter_ids=authorized_chunk_ids,
        authorized_text_paragraph_ids=[],
    )


def _pushed_case_for(annotation: BoundChapterAnnotation) -> list[PendingCase]:
    """2026-08-11 用于构造模型 push 登记的对话疑点案例（携带 dialogue_id）

    2026-09-13 登记即进池后案例行 id 就是 target_key，而 id 是全库主键：
    target_key 加 uuid 后缀，避免跨用例复用同一字面量时撞主键。
    """
    pending: list[PendingCase] = []
    for chunk in annotation.chunks:
        for dialogue in chunk.dialogues:
            pending.append(
                PendingCase(
                    type="dialogue_speaker",
                    chunk_id=chunk.chunk_id,
                    keys=[dialogue.content, "说话人"],
                    description=f"确认对话“{dialogue.content[:40]}”的说话人",
                    target_key=f"pushed-target-key-{uuid4().hex[:8]}",
                    target_ref={
                        "kind": "dialogue_speaker",
                        "dialogue_id": dialogue.candidate_key,
                        "chunk_id": chunk.chunk_id,
                        "keys": [dialogue.content, "说话人"],
                    },
                )
            )
    return pending


def _result(
    *,
    run_id: str,
    chapter_id: int,
    annotation: BoundChapterAnnotation,
    resolved_cases: list[ResolvedCase] | None = None,
    pushed_cases: list[PendingCase] | None = None,
    authorized_chunk_ids: list[int] | None = None,
    entity_names: list[str] | None = None,
) -> AgentRunResult:
    """2026-08-07 用于构造新合同 AgentRunResult

    2026-09-04 单一写面：实体经 entity_ops 走操作日志（不再有 payload 图副本）。
    """
    return AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=annotation,
        resolved_cases=resolved_cases or [],
        pushed_cases=pushed_cases or _pushed_case_for(annotation),
        entity_ops=[
            {
                "name": name,
                "entity_type": "character",
                "tags": [],
                "description": None,
                "attributes": {},
                "chapter_id": chapter_id,
            }
            for name in entity_names or []
        ],
        audit=_audit(
            authorized_chunk_ids=authorized_chunk_ids or [annotation.chunks[0].chunk_id],
        ),
    )


def _count(session, model, run_id: str) -> int:
    """2026-08-07 用于按 run 统计完成事务相关持久化行数"""
    return int(session.execute(select(func.count()).select_from(model).where(model.run_id == run_id)).scalar_one())


def test_complete_annotation_run_commits_case_and_is_idempotent(db_session) -> None:
    """2026-08-11 用于验证 push 案例与对话记录同时提交且重复完成保持幂等"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["“住手”回荡"],
        title="完成事务成功",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    annotation = _annotation(chunk_id=1, text="“住手”回荡", unresolved_dialogue=True)
    result = _result(
        run_id=run_id,
        chapter_id=1,
        annotation=annotation,
    )

    first = complete_annotation_run(
        result=result,
        session_factory=factory,
    )
    second = complete_annotation_run(
        result=result,
        session_factory=factory,
    )

    db_session.rollback()
    case = db_session.execute(select(CasePoolCase).where(CasePoolCase.run_id == run_id)).scalar_one()
    dialogue = db_session.execute(select(DialogueRecord).where(DialogueRecord.run_id == run_id)).scalar_one()

    assert first == second
    assert first.created_cases[0].id == case.id
    assert case.case_type == "dialogue_speaker"
    assert case.chapter_id == 1
    assert case.target_ref["dialogue_id"] == dialogue.candidate_key
    assert dialogue.speaker is None
    assert dialogue.confidence == "medium"
    assert dialogue.is_inner_monologue is False
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 1
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 1
    assert _count(db_session, DialogueRecord, run_id) == 1


def test_dialogue_resolution_updates_dialogue_record(
    db_session,
) -> None:
    """2026-08-11 用于验证后文 dialogue 动作解决直接更新对话记录表"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["“住手”回荡", "顾霜喝道"],
        chapter_ids=[1, 2],
        title="后文确认说话人",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    first_annotation = _annotation(
        chunk_id=1,
        text="“住手”回荡",
        unresolved_dialogue=True,
    )
    first = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=1,
            annotation=first_annotation,
        ),
        session_factory=factory,
    )
    db_session.rollback()
    case = db_session.get(CasePoolCase, first.created_cases[0].id)
    assert case is not None
    resolved = ResolvedCase(
        case_id=case.id,
        action="dialogue",
        type=case.case_type,
        speaker="顾霜",
        reason="后文点明顾霜",
        target_key=case.target_key,
        target_ref=dict(case.target_ref),
    )
    second_annotation = _annotation(
        chunk_id=2,
        text="顾霜喝道",
    )
    second = complete_annotation_run(
        result=_result(
            run_id=run_id,
            chapter_id=2,
            annotation=second_annotation,
            resolved_cases=[resolved],
            authorized_chunk_ids=[1, 2],
            entity_names=["顾霜"],
        ),
        session_factory=factory,
    )

    db_session.rollback()
    dialogue = db_session.execute(select(DialogueRecord).where(DialogueRecord.run_id == run_id)).scalar_one()
    resolved_case = db_session.get(CasePoolCase, case.id)
    mapping = db_session.execute(
        select(CaseResolutionMapping).where(
            CaseResolutionMapping.run_id == run_id,
            CaseResolutionMapping.case_id == case.id,
        )
    ).scalar_one()

    assert dialogue.candidate_key == case.target_ref["dialogue_id"]
    assert dialogue.speaker == "顾霜"
    assert resolved_case is not None and resolved_case.state == "resolved"
    assert mapping.target_dialogue_id == dialogue.dialogue_id
    assert mapping.resolution["action"] == "dialogue"
    assert second.resolved_cases[0].case_id == case.id
    assert second.resolved_cases[0].action == "dialogue"


def test_complete_annotation_run_rolls_back_everything_when_persist_fails(db_session) -> None:
    """2026-08-10 用于验证完成事务任一步失败时全部章节结果同时回滚（审计独立不受影响）"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["“住手”回荡"],
        title="完成事务回滚",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    annotation = _annotation(chunk_id=1, text="“住手”回荡", unresolved_dialogue=True)

    with patch(
        "src.workflows.annotate_helpers.storage.persist_completion_graph",
        side_effect=RuntimeError("persist failed"),
    ):
        with pytest.raises(RuntimeError, match="persist failed"):
            complete_annotation_run(
                result=_result(
                    run_id=run_id,
                    chapter_id=1,
                    annotation=annotation,
                ),
                session_factory=factory,
            )

    db_session.rollback()
    for model in (
        ChapterAnnotationRecord,
        CasePoolCase,
        CaseResolutionMapping,
        DialogueRecord,
        ChapterAnnotationRecord,
    ):
        assert _count(db_session, model, run_id) == 0


def test_load_completion_result_reads_existing_chapter_without_writes(db_session) -> None:
    """2026-08-07 用于验证已冻结章节可回读同一完成结果而不新增版本"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜喝道"],
        title="完成结果回读",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    annotation = _annotation(chunk_id=1, text="顾霜喝道")
    expected = complete_annotation_run(
        result=_result(run_id=run_id, chapter_id=1, annotation=annotation, entity_names=["顾霜"]),
        session_factory=factory,
    )

    db_session.rollback()
    actual = load_completion_result(db_session, run_id=run_id, chapter_id=1)

    assert actual == expected
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 1
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 1


def test_missing_resolved_case_rolls_back_before_annotation_write(db_session) -> None:
    """2026-08-07 用于验证无法锁定 resolved 案例时不写任何章节结果"""
    novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜喝道"],
        title="来源案例锁定失败",
    )
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    annotation = _annotation(chunk_id=1, text="顾霜喝道")
    missing = ResolvedCase(
        case_id="missing-case",
        action="close",
        type="dialogue_speaker",
        reason="无法确认",
        target_key="missing-target",
        target_ref={
            "kind": "dialogue_speaker",
            "dialogue_id": "dlg_missing",
            "chunk_id": 1,
        },
    )

    with pytest.raises(ValueError, match="无法锁定全部 resolved cases"):
        complete_annotation_run(
            result=_result(
                run_id=run_id,
                chapter_id=1,
                annotation=annotation,
                resolved_cases=[missing],
                entity_names=["顾霜"],
            ),
            session_factory=factory,
        )

    db_session.rollback()
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 0
    assert _count(db_session, ChapterAnnotationRecord, run_id) == 0


# ---------------------------------------------------------------------------
# 2026-09-11 章内并行 §14 过渡补丁：resolved_cases 按 case_id fold 合并
# 背景：run e84339d1 第 20 章两个子块各自解决同一批案例（交集 3 条），
# 合并直接拼接触发 _validate_locked_cases 唯一性校验整章回滚。
# ---------------------------------------------------------------------------


def _foreshadowing_case(case_id: str, *, reason: str, foreshadowing_event_id: str | None) -> ResolvedCase:
    return ResolvedCase(
        case_id=case_id,
        action="foreshadowing",
        type="伏笔疑点",
        reason=reason,
        target_key=f"key-{case_id}",
        target_ref={"kind": "伏笔疑点", "chunk_id": 20},
        foreshadowing_action="reinforce",
        foreshadowing_root_event_id="evt-root",
        foreshadowing_event_id=foreshadowing_event_id,
    )


def test_fold_resolved_cases_merges_duplicate_case_ids_from_two_blocks() -> None:
    """同一案例被两子块各解决一次：字段级后值覆盖、reason 拼接、保持首现顺序"""
    block_a = _foreshadowing_case("case-1", reason="A块引入段写埋设", foreshadowing_event_id="evt-a")
    block_b = _foreshadowing_case("case-1", reason="B块坐实段写确认", foreshadowing_event_id="evt-b")
    other = _foreshadowing_case("case-2", reason="仅A块解决", foreshadowing_event_id="evt-a2")

    folded = _fold_resolved_cases([block_a, block_b, other])

    assert [item.case_id for item in folded] == ["case-1", "case-2"]
    merged = folded[0]
    assert merged.reason == "A块引入段写埋设\nB块坐实段写确认"
    assert merged.foreshadowing_event_id == "evt-b"  # 挂树事件 id 取后者
    assert merged.target_key == "key-case-1"


def test_fold_resolved_cases_keeps_empty_later_fields() -> None:
    """后值仅在非空时覆盖：后块未填期望回收族（可空字段）不清掉前块的值"""
    block_a = _foreshadowing_case("case-1", reason="先到", foreshadowing_event_id="evt-a")
    block_a = block_a.model_copy(update={"expected_payoff_family": "守护"})
    block_b = _foreshadowing_case("case-1", reason="后到", foreshadowing_event_id="evt-b")

    folded = _fold_resolved_cases([block_a, block_b])

    assert len(folded) == 1
    assert folded[0].expected_payoff_family == "守护"
    assert folded[0].foreshadowing_event_id == "evt-b"
    assert folded[0].reason == "先到\n后到"


def test_fold_resolved_cases_covers_fact_path_duplicate() -> None:
    """fact 路径（relation_change_ops 还原）与 foreshadowing 路径同 case_id 在同一暴露面折叠"""
    from src.workflows.annotate_helpers.storage import _graph_fact_resolved_cases

    class _ResultStub:
        relation_change_ops = [
            {
                "case_id": "case-1",
                "case_type": "关系疑点",
                "reason": "fact 路径裁决",
                "target_key": "key-case-1",
                "target_ref": {"kind": "关系疑点", "chunk_id": 20},
                "from_entity": "白芷",
                "to_entity": "秦穆",
                "relation_type": "盟友",
                "change_kind": "assert",
            }
        ]

    foreshadowing = _foreshadowing_case("case-1", reason="伏笔路径裁决", foreshadowing_event_id="evt-a")
    merged = _fold_resolved_cases([foreshadowing, *_graph_fact_resolved_cases(_ResultStub())])

    assert len(merged) == 1
    assert merged[0].action == "fact"  # 后值覆盖 action
    assert merged[0].reason == "伏笔路径裁决\nfact 路径裁决"


def test_folded_resolved_cases_pass_locked_case_validation() -> None:
    """折叠后通过 _validate_locked_cases 唯一性校验（ch20 崩溃点的回归门）"""
    from types import SimpleNamespace

    from src.workflows.annotate_helpers.storage import _validate_locked_cases

    block_a = _foreshadowing_case("case-1", reason="A", foreshadowing_event_id="evt-a")
    block_b = _foreshadowing_case("case-1", reason="B", foreshadowing_event_id="evt-b")
    folded = _fold_resolved_cases([block_a, block_b])
    row = SimpleNamespace(
        id="case-1",
        state="active",
        case_type="伏笔疑点",
        target_key="key-case-1",
        target_ref={"kind": "伏笔疑点", "chunk_id": 20},
    )
    _validate_locked_cases(resolved_cases=folded, rows=[row])
