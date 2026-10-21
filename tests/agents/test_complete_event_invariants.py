"""声明身份、包含及真实来源边界"""

import json

import pytest

from src.agents.annotation.agent import AnnotationAgent
from src.event_bus import EventBus
from src.event_trees.organization import EventOrganizationDraft, OrganizationEvidence
from tests.agents.test_complete_event_work import declaration_code, execution_for, save_and_confirm
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import add_diagnosis_context, report_case_anchor
from tests.support.storage_fixtures import storage_factory, storage_for


@pytest.fixture
async def draft_case(db_session):
    novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜寻路并点灯。"])
    agent = AnnotationAgent(EventBus(), run_id, storage_factory(lambda: db_session), novel_id=novel_id)
    execution, runtime = execution_for(agent, db_session, 1)
    result = json.loads(
        await runtime.execute(declaration_code("search", "寻路") + "\n" + declaration_code("lamp", "点灯"))
    )
    assert not result.get("failed"), result
    await save_and_confirm(agent, db_session, execution)
    # 诊断整轮身份与报告级真实尝试：草案的 producer 是真实执行，不借用占位串
    session_id, agent_id = add_diagnosis_context(db_session, run_id)
    draft = EventOrganizationDraft(storage_for(db_session), run_id, session_id)
    draft.fixture_session = db_session
    draft.case_id = report_case_anchor(run_id)
    draft.producer_agent_id = agent_id
    yield draft
    agent.close()


def event(draft, key, child_ids=(), **kwargs):
    result = draft.event(
        key=key,
        title=key,
        problem="待解决",
        summary=key,
        event_type="探寻",
        status="ongoing",
        reason="原文中的整体行动",
        from_chapter_id=1,
        to_chapter_id=1,
        evidence=[OrganizationEvidence(paragraph_id=0)],
        **kwargs,
    )


def test_event_key_replay_is_idempotent_and_content_cannot_change(draft_case):
    draft = draft_case
    first = event(draft, "整体行动")
    assert event(draft, "整体行动") == first
    with pytest.raises(ValueError):
        event(draft, "整体行动", progress="不可覆盖")


def test_containment_cycle_rejected_at_submission_and_explicitly_retractable(draft_case):
    draft = draft_case
    children = list(draft._all_events())
    parent = event(draft, "整体行动", children)
    with pytest.raises(ValueError, match="成环"):
        draft.contain(parent_event_id=child, child_event_id=parent, reason="反向包含候选", evidence=evidence)
    assert len(draft.containments) == 1
    draft.retract(kind="contain", identifier=f"{parent}/{child}", reason="明确撤回包含候选", evidence=evidence)
    assert draft.containments == {}
    assert draft._parents() == {}


def test_changed_source_and_duplicate_frozen_event_rejected(draft_case):
    from pydantic import ValidationError


    draft = draft_case
    child = next(iter(draft._all_events()))
    parent = event(draft, "整体行动", [child])
    draft.retract(
        kind="identity",
        identifier=identifier,
        reason="撤回引用已改写来源的候选",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    assert not draft.containments
    assert parent in draft.events
