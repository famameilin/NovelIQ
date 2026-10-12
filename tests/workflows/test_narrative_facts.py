"""真实程序工具与提交恢复验证情节推进及无 case 的伏笔动作"""

from unittest.mock import patch

import pytest
from sqlalchemy import select

from src.metrics.queries.progression import ProgressionQuery
from src.storage.models import EventNode, ForeshadowingAction, GraphFact
from src.workflows.annotate import run_annotate
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.workflows.test_annotation_work_pipeline import ProgramModel


@pytest.mark.asyncio
async def test_progression_and_explicit_actions_survive_save_and_resume(db_session):
    novel_id, run_id = create_run_with_chunks(db_session, texts=["封信藏着旧事。印章再次出现。信件揭开旧事。"])
    model = ProgramModel(
        'event(el="letter", isroot=True, description="旧信暗示隐情", '
        'evidence=1, isforeshadowing=True, confidence="high")\n'
        'roots = search_events(query="旧信")\n'
        'root = roots["events"][0]["node_id"]\n'
        'foreshadow_action(root_event_id=root, action_type="reinforce", evidence=1)\n'
        'foreshadow_action(root_event_id=root, action_type="payoff", evidence=1)\n'
        'progression(subject_title="旧信之谜", description="印章揭示旧事", '
        'before="来历未知", after="确认与旧事相关", evidence=1)\n'
        'metric(summary="旧信揭谜", emotional_valence=0, narrative_function="转折")\nfinish()'
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (1, 0, 1)
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (1, 0, 1)
    assert model.calls == 1
    db_session.expire_all()
    actions = list(db_session.scalars(select(ForeshadowingAction).where(ForeshadowingAction.run_id == run_id)))
    assert {item.action_type for item in actions} == {"setup", "reinforce", "payoff"}
    assert len(actions) == 3
    fact = db_session.scalar(
        select(GraphFact).where(GraphFact.run_id == run_id, GraphFact.fact_type == "plot_progression")
    )
    assert set(fact.content["operation"]) == {"subject_id", "subject_title", "description", "before", "after"}
    assert fact.evidence[0]["text"] == "封信藏着旧事。印章再次出现。信件揭开旧事。"
    result = ProgressionQuery(db_session, run_id).fetch()
    assert result["total"] == 4
    assert next(item for item in result["states"] if item["dimension"] == "foreshadowing")["state"] == "疑似回收"


@pytest.mark.asyncio
async def test_foreshadowing_state_follows_passage_order_not_tool_calls(db_session):
    novel_id, run_id = create_run_with_chunks(
        db_session, texts=["旧信留下隐情。\n\n印章再次出现。\n\n信件终于揭开旧事。"], chapter_ids=[1]
    )
    model = ProgramModel(
        'event(el="letter", isroot=True, description="旧信暗示隐情", '
        'evidence=1, isforeshadowing=True, confidence="high")\n'
        'roots = search_events(query="旧信")\nroot = roots["events"][0]["node_id"]\n'
        'foreshadow_action(root_event_id=root, action_type="payoff", evidence=3)\n'
        'foreshadow_action(root_event_id=root, action_type="reinforce", evidence=2)\n'
        'metric(summary="旧信揭谜", emotional_valence=0, narrative_function="转折")\nfinish()'
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (1, 0, 1)
    db_session.expire_all()
    result = ProgressionQuery(db_session, run_id).fetch()
    assert [item["action"] for item in result["changes"]] == ["setup", "reinforce", "payoff"]
    assert result["changes"][-1]["before"] == "已强化"
    assert result["states"][0]["state"] == "疑似回收"
    root = db_session.scalar(select(EventNode).where(EventNode.run_id == run_id))
    assert root.foreshadowing_status == "likely_paid_off"
