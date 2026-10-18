"""真实程序工具与提交恢复验证情节推进及无 case 的伏笔动作（全库 3NF 新读写面）"""

import json
from unittest.mock import patch

import pytest
from sqlalchemy import and_, select

from src.agents.diagnosis.tools import build_diagnosis_tools
from src.diagnosis.queries import DiagnosisQueries
from src.event_trees.read.foreshadowing import calculate_foreshadow_expectation, fetch_foreshadowing_trees
from src.event_trees.read.forest import EventForestQuery
from src.metrics.queries.plotline import PlotlineQuery
from src.storage.models import (
    AgentToolCall,
    Chapter,
    ChapterAnnotation,
    EventDeclaration,
    EventForeshadowingAction,
    Execution,
    GraphFact,
    ModelCall,
    Paragraph,
    SourceEvidence,
)
from src.workflows.annotate import run_annotate
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import (
    close_structure,
    first_paragraph,
    identity_every_declaration,
    publish_declarations,
    publish_draft,
)
from tests.support.storage_fixtures import fixture_id, storage_for
from tests.workflows.test_annotation_work_pipeline import ProgramModel


def _run_executions(run_id: str):
    """本 run 的真实尝试执行（执行行直接携带运行归属）"""
    return select(Execution.execution_id).where(Execution.run_id == run_id)


def _run_actions(db_session, run_id: str) -> list[EventForeshadowingAction]:
    return list(
        db_session.scalars(
            select(EventForeshadowingAction)
            .where(EventForeshadowingAction.producer_execution_id.in_(_run_executions(run_id)))
            .order_by(EventForeshadowingAction.operation_order, EventForeshadowingAction.action_id)
        )
    )


def _run_plotlines(db_session, run_id: str) -> list[GraphFact]:
    """情节推进形状：主体标题非空即推进事实（运行从直接生产执行取得）"""
    return list(
        db_session.scalars(
            select(GraphFact).where(
                GraphFact.direct_producer_execution_id.in_(_run_executions(run_id)),
                GraphFact.plotline_subject_title.is_not(None),
            )
        )
    )


def _declaration_ids_by_chapter(db_session, run_id: str) -> list[str]:
    """本 run 全部不可变声明，按章节顺序（章序从正式产物行的自身归属取得）"""
    return list(
        db_session.scalars(
            select(EventDeclaration.declaration_id)
            .join(ChapterAnnotation, ChapterAnnotation.record_id == EventDeclaration.record_id)
            .join(
                Chapter,
                and_(
                    Chapter.run_id == ChapterAnnotation.run_id,
                    Chapter.chapter_id == ChapterAnnotation.chapter_id,
                ),
            )
            .where(ChapterAnnotation.run_id == run_id)
            .order_by(Chapter.sequence, EventDeclaration.created_at)
        )
    )


def _plotline_evidence_text(db_session, run_id: str, fact: GraphFact) -> str:
    """推进事实的原文证据：证据行只存段号与字符区间，文本读本 run 段落正文（段号是 run 内身份）"""
    row = db_session.execute(
        select(SourceEvidence, Paragraph.text)
        .join(
            Paragraph,
            and_(Paragraph.run_id == run_id, Paragraph.paragraph_id == SourceEvidence.paragraph_id),
        )
        .where(SourceEvidence.graph_fact_id == fact.graph_fact_id)
        .order_by(SourceEvidence.ordinal)
    ).first()
    assert row is not None
    evidence, text = row
    return str(text)[int(evidence.start_char) : int(evidence.end_char)]


@pytest.mark.asyncio
async def test_plotline_and_explicit_actions_survive_save_and_resume(db_session):
    novel_id, run_id = create_run_with_chunks(db_session, texts=["封信藏着旧事。印章再次出现。信件揭开旧事。"])
    model = ProgramModel(
        'event(el="letter", title="旧信", problem="信中隐情是什么", summary="旧信暗示隐情", '
        'event_type="悬念", status="ongoing", '
        'evidence=1, isforeshadowing=True, confidence="high")\n'
        'roots = search_events(query="旧信")\n'
        'root = roots["events"][0]["declaration_id"]\n'
        'foreshadow_action(source_declaration_id=root, action_type="reinforce", evidence=1)\n'
        'foreshadow_action(source_declaration_id=root, action_type="payoff", evidence=1)\n'
        'plotline(subject_title="旧信之谜", description="印章揭示旧事", '
        'before="来历未知", after="确认与旧事相关", evidence=1, declaration_id=root)\n'
        'metric(summary="旧信揭谜", emotional_valence=0, narrative_function="转折")\nfinish()'
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
    assert model.calls == 1
    db_session.expire_all()
    actions = _run_actions(db_session, run_id)
    assert {item.action_type for item in actions} == {"setup", "reinforce", "payoff"}
    assert len(actions) == 3
    fact = _run_plotlines(db_session, run_id)[0]
    assert fact.plotline_subject_title == "旧信之谜"
    assert fact.plotline_description == "印章揭示旧事"
    assert (fact.plotline_before, fact.plotline_after) == ("来历未知", "确认与旧事相关")
    assert fact.business_call_id is not None
    assert _plotline_evidence_text(db_session, run_id, fact) == "封信藏着旧事。印章再次出现。信件揭开旧事。"
    assert calculate_foreshadow_expectation(storage_for(db_session), run_id) == pytest.approx(1.0)
    source = DiagnosisQueries(storage_for(db_session)).fetch_foreshadowing_sources(run_id)[0]
    assert source["declaration_id"] == actions[0].source_declaration_id
    assert {item["action_type"] for item in source["source_actions"]} == {"setup", "reinforce", "payoff"}
    # 发布事件身份后同一批动作才成为正式伏笔树与章级投影（未发布动作没有可读事件身份）
    publish_declarations(db_session, run_id)
    assert calculate_foreshadow_expectation(storage_for(db_session), run_id) == pytest.approx(1.0)
    trees = fetch_foreshadowing_trees(storage_for(db_session), run_id)
    assert len(trees) == 1
    assert trees[0].status == "likely_paid_off"
    assert trees[0].payoff_likelihood == "high"
    # 实际诊断工具读取同一份已保存来源，统计与图谱非本测试范围的数据接口单独置空
    with (
        patch("src.storage.repositories.StatsRepository") as stats,
        patch("src.agents.diagnosis.tools.graph_signals", return_value={}),
    ):
        stats.return_value.fetch_global_stats_dict.return_value = {}
        tools = {
            tool.name: tool
            for tool in build_diagnosis_tools(
                storage_for(db_session), run_id, role="report", execution_id=fixture_id(__name__, "read-contract")
            )
        }
        metrics = json.loads(tools["read_metrics"].invoke({}))
    assert metrics["foreshadowing"] == [source]
    assert metrics["foreshadow_expectation"] == pytest.approx(1.0)
    result = PlotlineQuery(storage_for(db_session), run_id).fetch()
    assert result["total"] == 4
    assert next(item for item in result["states"] if item["dimension"] == "foreshadowing")["state"] == "疑似回收"


@pytest.mark.asyncio
async def test_foreshadowing_state_follows_passage_order_not_tool_calls(db_session):
    novel_id, run_id = create_run_with_chunks(
        db_session, texts=["旧信留下隐情。\n\n印章再次出现。\n\n信件终于揭开旧事。"], chapter_ids=[1]
    )
    model = ProgramModel(
        'event(el="letter", title="旧信", problem="信中隐情是什么", summary="旧信暗示隐情", '
        'event_type="悬念", status="ongoing", '
        'evidence=1, isforeshadowing=True, confidence="high")\n'
        'roots = search_events(query="旧信")\nroot = roots["events"][0]["declaration_id"]\n'
        'foreshadow_action(source_declaration_id=root, action_type="payoff", evidence=3)\n'
        'foreshadow_action(source_declaration_id=root, action_type="reinforce", evidence=2)\n'
        'metric(summary="旧信揭谜", emotional_valence=0, narrative_function="转折")\nfinish()'
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
    db_session.expire_all()
    publish_declarations(db_session, run_id)
    result = PlotlineQuery(storage_for(db_session), run_id).fetch()
    assert [item["action"] for item in result["changes"]] == ["setup", "reinforce", "payoff"]
    assert result["changes"][-1]["before"] == "已强化"
    assert result["states"][0]["state"] == "疑似回收"
    declaration = db_session.scalar(
        select(EventDeclaration).where(
            EventDeclaration.declaration_id.in_(_declaration_ids_by_chapter(db_session, run_id))
        )
    )
    assert declaration.is_foreshadowing_root is True
    snapshot = EventForestQuery(storage_for(db_session)).fetch_snapshot(run_id)
    assert snapshot.foreshadowing_edges[0].status == "likely_paid_off"
    assert snapshot.foreshadowing_edges[0].payoff_event_id is None


@pytest.mark.asyncio
async def test_event_reference_accepts_el_local_key(db_session):
    """事件回执同时给出 el 与节点 UUID；用回执里的 el 局部键引用事件也应生效，不再只认 UUID"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["旧信暗示隐情。\n\n印章揭示旧事。"])
    model = ProgramModel(
        'event(el="letter", title="旧信", problem="信中隐情是什么", summary="旧信暗示隐情", '
        'event_type="悬念", status="ongoing", '
        'evidence=1, isforeshadowing=True, confidence="high")\n'
        'plotline(subject_title="旧信之谜", description="印章揭示旧事", '
        'before="来历未知", after="确认相关", evidence=2, declaration_id="letter")\n'
        'foreshadow_action(source_declaration_id="letter", action_type="reinforce", evidence=2)\n'
        'metric(summary="旧信揭谜", emotional_valence=0, narrative_function="转折")\nfinish()'
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
    db_session.expire_all()
    assert len(_run_plotlines(db_session, run_id)) == 1
    assert {item.action_type for item in _run_actions(db_session, run_id)} == {"setup", "reinforce"}
    assert calculate_foreshadow_expectation(storage_for(db_session), run_id) == pytest.approx(0.72)


@pytest.mark.asyncio
async def test_independent_plotline_subject_needs_no_event_identity(db_session):
    """独立情节推进不依赖事件身份：发布前与发布后读面一致"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜放弃入门，转而决定寻访旧友。"])
    model = ProgramModel(
        'plotline(subject_title="寻友目标", description="改变目标", '
        'before="求入山门", after="寻访旧友", evidence=1)\n'
        'metric(summary="改换目标", emotional_valence=0, narrative_function="转折")\nfinish()'
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
    before = PlotlineQuery(storage_for(db_session), run_id).fetch()
    assert before["total"] == 1
    assert before["changes"][0]["subject_title"] == "寻友目标"
    assert before["changes"][0]["source_event_ids"] == []
    publish_declarations(db_session, run_id)
    after = PlotlineQuery(storage_for(db_session), run_id).fetch()
    # 发布只改变组织状态：独立推进的读取结果与来源事件集合保持一致
    assert after["total"] == before["total"] == 1
    assert after["changes"] == before["changes"]


@pytest.mark.asyncio
async def test_foreshadow_expectation_uses_frozen_and_published_identity(db_session):
    novel_id, run_id = create_run_with_chunks(
        db_session, texts=["旧信暗示秘密。", "旧信重现，秘密已经揭晓。"], chapter_ids=[1, 2]
    )
    programs = [
        f'event(el="letter", title="旧信之谜", problem="秘密是什么", summary="{summary}", '
        f'event_type="悬念", status="ongoing", evidence=1, isforeshadowing=True, confidence="high")\n'
        + ('foreshadow_action(source_declaration_id="letter", action_type="payoff", evidence=1)\n' if index else "")
        + 'metric(summary="旧信", emotional_valence=0, narrative_function="转折")\nfinish()'
        for index, summary in enumerate(["旧信暗示秘密", "旧信揭露秘密"])
    ]
    with patch("src.model_pool.llm.build_chat_model", return_value=ProgramModel(programs)):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (2, 0, 2)
    failures = list(
        db_session.scalars(
            select(AgentToolCall)
            .join(ModelCall, ModelCall.call_id == AgentToolCall.call_id)
            .where(
                ModelCall.execution_id.in_(_run_executions(run_id)),
                AgentToolCall.error.is_not(None),
            )
        )
    )
    assert not failures, [(item.tool_name, item.error) for item in failures]
    declaration_ids = _declaration_ids_by_chapter(db_session, run_id)
    assert len(declaration_ids) == 2
    # 冻结身份未发布时，显式绑定下的期望与存储读面不同；发布后两者一致
    draft, _meta = identity_every_declaration(db_session, run_id, groups=[declaration_ids])
    close_structure(db_session, draft, evidence_paragraph_id=int(first_paragraph(db_session, run_id).paragraph_id))
    bindings = {
        declaration_id: event_id for event_id, event in draft.events.items() for declaration_id in event.declaration_ids
    }
    frozen = DiagnosisQueries(storage_for(db_session)).calculate_foreshadow_expectation(
        run_id, declaration_bindings=bindings
    )
    assert frozen == pytest.approx(1.0)
    assert calculate_foreshadow_expectation(storage_for(db_session), run_id) < frozen
    publish_draft(db_session, run_id, draft)
    assert calculate_foreshadow_expectation(storage_for(db_session), run_id) == pytest.approx(frozen)


@pytest.mark.asyncio
async def test_foreshadow_expectation_tolerates_unbound_identity(db_session):
    """身份覆盖缺口不阻止计算：未绑定事件身份的伏笔根按自身身份单独成组"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["旧信暗示秘密。"])
    program = (
        'event(el="letter", title="旧信之谜", problem="秘密是什么", summary="旧信暗示秘密", '
        'event_type="悬念", status="ongoing", evidence=1, isforeshadowing=True, confidence="high")\n'
        'metric(summary="旧信", emotional_valence=0, narrative_function="转折")\nfinish()'
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=ProgramModel(program)):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
    db_session.expire_all()
    expectation = DiagnosisQueries(storage_for(db_session)).calculate_foreshadow_expectation(
        run_id, declaration_bindings={}
    )
    assert expectation is not None and 0.0 <= expectation <= 1.0
    assert expectation == calculate_foreshadow_expectation(storage_for(db_session), run_id)
