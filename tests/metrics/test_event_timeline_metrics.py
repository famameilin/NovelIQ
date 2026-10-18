"""事件森林时间轴度量单元测试（一树一节点）

标注来源链与章级声明由夹具按正式关系写入，完整事件
经正式诊断发布链（EventOrganizationDraft → save_diagnosis_result）建立；断言只针对
时间轴读面的行为与输出，不复制文案或数量形状。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.agents.diagnosis.persistence import save_diagnosis_result
from src.diagnosis.schema import AgentAnalysis
from src.event_trees.organization import EventOrganizationDraft, OrganizationEvidence
from src.event_trees.read.forest import EventForestQuery
from src.metrics.event_timeline_metrics import serialize_event_timeline_node
from src.metrics.queries.timeline import build_event_timeline_plan
from src.storage import new_id
from src.storage.models import Paragraph
from src.storage.repositories import ChapterRepository
from src.storage.repositories.organization_writes import register_diagnosis_execution, register_diagnosis_session
from src.storage.repositories.paragraph import insert_paragraph_tension_observations
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import report_case_anchor
from tests.support.storage_fixtures import storage_for
from tests.support.timeline_contract_helpers import (
    create_chapter_annotation_source,
    save_event_declaration,
)

#: 三章各自的声明参与者（事件参与者即读面的人物来源）
_THREE_TREE_PARTICIPANTS = [["顾霜"], ["顾霜", "苏映雪"], ["顾霜"]]

#: 三章张力输入的 z 观测（读面按 sigmoid 投影，单调顺序即输入顺序）
_THREE_TREE_TENSIONS = [0.4, 0.9, 0.5]


def _publish_one_event_per_declaration(
    db_session,
    *,
    run_id: str,
    declarations: list[str],
    evidence_paragraph_id: int,
    character_names: list[str],
) -> None:
    """经正式诊断发布链把每条声明收口为一个完整事件（互不包含、互不相同）"""
    session_id = new_id()
    execution_id = new_id()
    register_diagnosis_session(db_session, run_id=run_id, session_id=session_id)
    register_diagnosis_execution(db_session, run_id=run_id, execution_id=execution_id, role="report", attempt_number=1)
    draft = EventOrganizationDraft(storage_for(db_session), run_id, session_id)
    draft.fixture_session = db_session
    draft.case_id, draft.producer_invocation_id = report_case_anchor(run_id), execution_id
    rows = {row["declaration_id"]: row for row in draft.read_declarations(declarations)["items"]}

    def source_evidence(declaration_id: str) -> list[OrganizationEvidence]:
        return [OrganizationEvidence(paragraph_id=row["paragraph_id"]) for row in rows[declaration_id]["evidence"]]

    for index, declaration_id in enumerate(declarations):
        row = rows[declaration_id]
        draft.identity(
            key=f"event-{index + 1}",
            title=row["title"],
            problem=row["problem"],
            summary=row["summary"],
            event_type=row["event_type"],
            status=row["status"],
            progress=row["progress"],
            declaration_ids=[declaration_id],
            stage_order=[declaration_id],
            current_declaration_id=declaration_id,
            reason="读取夹具显式指定本声明组成一个事件身份",
            evidence=source_evidence(declaration_id),
        )
    for index, source in enumerate(declarations):
        for target in declarations[index + 1 :]:
            draft.compare_declarations(
                source_declaration_id=source,
                target_declaration_ids=[target],
                disposition="independent",
                reason="读取夹具显式判定两条声明为独立事件",
                evidence=source_evidence(source),
            )
    draft.review_declarations(list(declarations), reason="读取夹具已逐项核对不可变声明与原文")
    events = list(draft.events)
    structure_evidence = [OrganizationEvidence(paragraph_id=evidence_paragraph_id)]
    for index, source in enumerate(events):
        for target in events[index + 1 :]:
            draft.structure_review(
                source_event_id=source,
                target_event_id=target,
                disposition="independent",
                reason="读取夹具显式判定两事件互不包含",
                evidence=structure_evidence,
            )
    for event_id in events:
        draft.review_events([event_id], reason="读取夹具已核对正式身份与结构")
    organization = draft.finish()
    save_diagnosis_result(
        storage_for(db_session),
        run_id,
        AgentAnalysis(
            narrative_organization=organization,
            focus_characters=character_names[:1],
            main_characters=list(character_names),
            core_cast=list(character_names),
            arc_scores={name: 8.0 - index * 0.5 for index, name in enumerate(character_names)},
            genre_labels=["通用"],
            style_labels=["严肃"],
            diagnosis="事件时间轴度量夹具诊断",
            focus_structure="single" if len(character_names) == 1 else "dual",
        ),
    )


def _build_forest(
    db_session,
    *,
    texts: list[str],
    tensions: list[float],
    participants_by_chapter: list[list[str]] | None = None,
    title: str,
) -> str:
    """每章一条章级声明与一个完整事件，张力按 z 正式观测写入，返回 run_id"""
    chapter_ids = list(range(1, len(texts) + 1))
    _, run_id = create_run_with_chunks(db_session, texts=texts, chapter_ids=chapter_ids, title=title)
    groups = participants_by_chapter or [["顾霜"] for _ in chapter_ids]
    declarations: list[str] = []
    paragraph_ids: list[int] = []
    for index, chapter_id in enumerate(chapter_ids):
        record_id, _execution_id = create_chapter_annotation_source(db_session, run_id=run_id, chapter_id=chapter_id)
        paragraph = db_session.scalar(
            select(Paragraph)
            .where(Paragraph.run_id == run_id, Paragraph.chapter_id == chapter_id)
            .order_by(Paragraph.paragraph_id)
        )
        paragraph_ids.append(paragraph.paragraph_id)
        declarations.append(
            save_event_declaration(
                db_session,
                run_id=run_id,
                record_id=record_id,
                chapter_id=chapter_id,
                local_key=f"chapter-{chapter_id}",
                title=f"第{chapter_id}章事件",
                problem=f"第{chapter_id}章事件问题",
                summary=paragraph.text,
                participants=[{"name": name, "entity_type": "character", "role": "主体"} for name in groups[index]],
            )
        )
    character_names = sorted({name for group in groups for name in group})
    _publish_one_event_per_declaration(
        db_session,
        run_id=run_id,
        declarations=declarations,
        evidence_paragraph_id=paragraph_ids[0],
        character_names=character_names,
    )
    insert_paragraph_tension_observations(db_session, run_id, list(zip(paragraph_ids, tensions, strict=True)))
    db_session.commit()
    return run_id


def _build_forest_three_trees(db_session, *, tensions: list[float] | None = None) -> str:
    """构造三章事件用于验证重要性分级与推进进度"""
    return _build_forest(
        db_session,
        texts=["章一文本。", "章二文本。", "章三文本。"],
        tensions=tensions if tensions is not None else _THREE_TREE_TENSIONS,
        participants_by_chapter=_THREE_TREE_PARTICIPANTS,
        title="事件时间轴分位数",
    )


def _plan(db_session, run_id: str):
    snapshot = EventForestQuery(storage_for(db_session)).fetch_snapshot(run_id)
    return build_event_timeline_plan(run_id, ChapterRepository(db_session), storage_for(db_session), snapshot)


def test_level_quantile_66_33(db_session) -> None:
    run_id = _build_forest_three_trees(db_session)
    plan = _plan(db_session, run_id)
    assert {node.anchor_chapter_id for node in plan.nodes} == {1, 2, 3}
    assert {node.level for node in plan.nodes} <= {1, 2, 3}
    # 分位分级：最高重要性落到 1，等级随重要性下降不升
    ranked = sorted(plan.nodes, key=lambda node: node.importance_score, reverse=True)
    ranked_levels = [node.level for node in ranked]
    assert ranked_levels[0] == 1
    assert ranked_levels == sorted(ranked_levels)
    # 无因果出入时重要性只随章张力分位变化：张力更高的章其事件排名更前
    assert [node.anchor_chapter_id for node in ranked] == [2, 3, 1]


def test_level_all_equal_only_max_is_1(db_session) -> None:
    """全相等时仅 max 为 1 其余 2"""
    run_id = _build_forest(
        db_session,
        texts=["章一", "章二", "章三"],
        tensions=[0.5, 0.5, 0.5],
        title="等分",
    )
    plan = _plan(db_session, run_id)
    assert len({node.importance_score for node in plan.nodes}) == 1
    levels = [node.level for node in plan.nodes]
    assert levels.count(1) == 1, f"全相等时仅 max 为1其余为2，实际 levels={levels}"
    assert levels.count(2) == len(levels) - 1


def test_progress_calculation(db_session) -> None:
    run_id = _build_forest_three_trees(db_session)
    plan = _plan(db_session, run_id)
    by_chapter = {node.anchor_chapter_id: node for node in plan.nodes}
    # 推进位置随阅读顺序单调前进，最末章到达全文终点
    assert by_chapter[1].progress < by_chapter[2].progress < by_chapter[3].progress
    assert by_chapter[3].progress == pytest.approx(1.0)
    for node in plan.nodes:
        assert 0 <= node.start_progress <= node.end_progress <= 1
        assert node.start_chapter_id <= node.anchor_chapter_id <= node.end_chapter_id


def test_phase_mapping(db_session) -> None:
    run_id = _build_forest_three_trees(db_session)
    plan = _plan(db_session, run_id)
    assert plan.total_chapters == 3
    phase_names = {phase.name for phase in plan.phases}
    for node in plan.nodes:
        assert node.phase_name in phase_names
        anchor_phase = [p for p in plan.phases if p.start <= node.anchor_chapter_id <= p.end]
        assert anchor_phase and node.phase_name == anchor_phase[0].name
    covered = sorted({chapter for phase in plan.phases for chapter in range(phase.start, phase.end + 1)})
    assert covered == [1, 2, 3]


def test_importance_score_formula(db_session) -> None:
    run_id = _build_forest_three_trees(db_session)
    plan = _plan(db_session, run_id)
    by_chapter = {node.anchor_chapter_id: node for node in plan.nodes}
    # 主链长度与因果出入相同时，张力分位决定重要性高低
    assert by_chapter[2].importance_score > by_chapter[3].importance_score > by_chapter[1].importance_score
    for node in plan.nodes:
        payload = serialize_event_timeline_node(node)
        assert payload["node_type"] == "event"
        assert payload["tree_id"] == node.tree_id
        assert payload["root_event_id"] == node.root_event_id
        assert payload["main_chain"] == [node.root_event_id]
        # 读面人物来自声明参与者，实体投影给出正式名字与角色大类
        expected = _THREE_TREE_PARTICIPANTS[node.anchor_chapter_id - 1]
        assert sorted(item["entity"]["name"] for item in payload["participants"]) == sorted(expected)
        assert {item["entity"]["entity_type"] for item in payload["participants"]} == {"character"}


def test_empty_snapshot_returns_no_nodes_but_phases(db_session) -> None:
    _, run_id = create_run_with_chunks(db_session, texts=["章一"], chapter_ids=[1], title="空")
    paragraph = db_session.scalar(select(Paragraph).where(Paragraph.run_id == run_id).order_by(Paragraph.paragraph_id))
    insert_paragraph_tension_observations(db_session, run_id, [(paragraph.paragraph_id, 0.6)])
    db_session.commit()
    snapshot = EventForestQuery(storage_for(db_session)).fetch_snapshot(run_id)
    assert snapshot is None
    plan = build_event_timeline_plan(
        run_id,
        ChapterRepository(db_session),
        storage_for(db_session),
        snapshot,
    )
    assert plan.nodes == []
    assert plan.total_chapters == 1
    assert len(plan.phases) >= 1
