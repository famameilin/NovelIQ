"""声明身份、包含及真实来源边界"""

import json

import pytest

from src.agents.annotation.agent import AnnotationAgent
from src.event_bus import EventBus
from src.event_trees.organization import EventOrganizationDraft
from src.event_trees.organization_models import OrganizationEvidence
from tests.agents.test_complete_event_work import declaration_code, execution_for, save_and_confirm
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import add_diagnosis_context, report_case_anchor
from tests.support.storage_fixtures import storage_factory, storage_for


@pytest.fixture
async def draft_case(db_session):
    novel_id, run_id = create_run_with_chunks(
        db_session, texts=["顾霜寻找山门，点燃一盏灯，打开旧信，核对地图，通知同伴。"]
    )
    agent = AnnotationAgent(EventBus(), run_id, storage_factory(lambda: db_session), novel_id=novel_id)
    execution, runtime = execution_for(agent, db_session, 1)
    result = json.loads(
        await runtime.execute(
            "\n".join(
                declaration_code(key, title)
                for key, title in (
                    ("search", "寻找山门"),
                    ("lamp", "点燃灯火"),
                    ("letter", "打开旧信"),
                    ("map", "核对地图"),
                    ("notice", "通知同伴"),
                )
            )
        )
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


def tree_for(draft, event_id: str) -> str:
    for item in draft.queues.values():
        if event_id in item.event_ids:
            return item.tree_id
    return draft.queue_graph().event_tree[event_id]


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
    tree_id = draft.queue(
        event_ids=[result["event_id"]], reason="独立行动", evidence=[OrganizationEvidence(paragraph_id=0)]
    )
    for child in child_ids:
        child_tree = tree_for(draft, child)
        draft.reference(
            parent_tree_id=tree_id,
            child_tree_id=child_tree,
            reason="整体行动包含子事件",
            evidence=[OrganizationEvidence(paragraph_id=0)],
        )
    return result["event_id"]


def test_event_key_replay_is_idempotent_and_content_cannot_change(draft_case):
    draft = draft_case
    first = event(draft, "整体行动")
    assert event(draft, "整体行动") == first
    with pytest.raises(ValueError):
        event(draft, "整体行动", progress="不可覆盖")


def test_queue_cycle_rejected_and_multiple_parents_preserved(draft_case):
    draft = draft_case
    children = list(draft._all_events())
    parent = event(draft, "整体行动", children)
    parent_tree = tree_for(draft, parent)
    children_tree = tree_for(draft, children[0])
    with pytest.raises(ValueError, match="成环"):
        draft.reference(
            parent_tree_id=children_tree,
            child_tree_id=parent_tree,
            reason="环",
            evidence=[OrganizationEvidence(paragraph_id=0)],
        )
    other = event(draft, "另一个整体")
    other_tree = tree_for(draft, other)
    draft.reference(
        parent_tree_id=other_tree,
        child_tree_id=children_tree,
        reason="双父",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    assert draft.queue_graph().event_parents(children[0]) == [parent, other]


def test_only_own_unsaved_reference_can_be_retracted(draft_case):
    draft = draft_case
    child = next(iter(draft._all_events()))
    parent = event(draft, "整体行动", [child])
    parent_tree = tree_for(draft, parent)
    child_tree = tree_for(draft, child)
    draft.retract(
        kind="reference",
        identifier=f"{parent_tree}/{child_tree}",
        reason="重新判断",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    assert not draft.queue_references
    assert parent in draft.events
