"""声明身份、冻结、包含及真实来源边界"""

import json

import pytest

from src.agents.annotation.agent import AnnotationAgent
from src.event_bus import EventBus
from src.event_trees.organization import EventOrganizationDraft, OrganizationEvidence
from tests.agents.test_complete_event_work import declaration_code, execution_for, save_and_confirm
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import add_diagnosis_context, report_case_anchor


@pytest.fixture
async def draft_case(db_session):
    novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜寻路并点灯。"])
    agent = AnnotationAgent(EventBus(), run_id, lambda: db_session, novel_id=novel_id)
    execution, runtime = execution_for(agent, db_session, 1)
    result = json.loads(await runtime.execute(declaration_code("search", "寻路")+"\n"+declaration_code("lamp", "点灯")))
    assert not result.get("failed"), result
    await save_and_confirm(agent, db_session, execution)
    # 诊断整轮身份与报告级真实尝试：草案的 producer 是真实执行，不借用占位串
    session_id, execution_id = add_diagnosis_context(db_session, run_id)
    draft = EventOrganizationDraft(db_session, run_id, session_id)
    draft.case_id = report_case_anchor(run_id)
    draft.producer_invocation_id = execution_id
    yield draft
    agent.close()


def event(draft, key, declaration_ids, **kwargs):
    return draft.identity(key=key, title=key, problem="待解决", summary=key, event_type="探寻", status="ongoing",
        declaration_ids=declaration_ids, stage_order=kwargs.pop("stage_order", declaration_ids),
        current_declaration_id=kwargs.pop("current_declaration_id", declaration_ids[-1]), reason="测试明确判断同一事件",
        evidence=[OrganizationEvidence(paragraph_id=0)], **kwargs)["event_id"]


def freeze_identities(draft, *, same):
    ids = list(draft._declarations())
    draft.review_declarations(ids, reason="已依据原文核对声明")
    draft.compare_declarations(source_declaration_id=ids[0], target_declaration_ids=[ids[1]],
        disposition="same_event" if same else "independent", reason="本例明确选择对应身份关系",
        evidence=[OrganizationEvidence(paragraph_id=0)])
    draft.freeze_identity()


def test_bad_source_rejected_and_identity_conflict_has_no_first_writer_priority(draft_case):
    draft = draft_case
    ids = list(draft._declarations())
    with pytest.raises(ValueError, match="不属于"):
        event(draft, "bad", [ids[0], "missing"])
    assert not draft.events
    first = event(draft, "first", [ids[0]])
    second = event(draft, "second", ids)
    assert set(draft.events) == {first, second}
    with pytest.raises(ValueError, match="相冲突"):
        freeze_identities(draft, same=True)
    assert set(draft.events) == {first, second}
    draft.retract(kind="identity", identifier=second, reason="明确撤回冲突候选",
                  evidence=[OrganizationEvidence(paragraph_id=0)])
    event(draft, "remaining", [ids[1]])
    freeze_identities(draft, same=False)


def test_containment_cycle_is_blocked_at_acceptance_and_explicitly_retractable(draft_case):
    draft = draft_case
    ids = list(draft._declarations())
    child, parent = event(draft, "child", [ids[0]]), event(draft, "parent", [ids[1]])
    freeze_identities(draft, same=False)
    evidence = [OrganizationEvidence(paragraph_id=0)]
    draft.contain(parent_event_id=parent, child_event_id=child, reason="独立事件组成", evidence=evidence)
    draft.contain(parent_event_id=child, child_event_id=parent, reason="矛盾候选保留待审", evidence=evidence)
    with pytest.raises(ValueError, match="环"):
        draft.review_events([child], reason="不能核对成环结构")
    assert len(draft.containments) == 2
    draft.retract(kind="contain", identifier=f"{child}/{parent}", reason="明确撤回成环候选", evidence=evidence)
    assert draft._parents() == {child: parent}


def test_changed_source_and_duplicate_frozen_event_rejected(draft_case):
    from pydantic import ValidationError

    from src.event_trees.organization import NarrativeOrganization
    from src.storage.models import EventDeclaration

    draft = draft_case
    ids = list(draft._declarations())
    identifier = event(draft, "invalid", ids)
    # 候选提交后来源正文被改写：冻结时来源哈希失效，不能冒充真实来源
    source = draft.session.get(EventDeclaration, ids[0])
    original_title = source.title
    source.title = "改写后的标题"
    draft.session.flush()
    with pytest.raises(ValueError, match="来源"):
        freeze_identities(draft, same=True)
    # 撤回引用已改写来源的候选，恢复来源原文后重新提交
    draft.retract(
        kind="identity",
        identifier=identifier,
        reason="撤回引用已改写来源的候选",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    source.title = original_title
    draft.session.flush()
    identifier = event(draft, "valid", ids)
    freeze_identities(draft, same=True)
    draft.review_events([identifier], reason="实际身份结构已核对")
    draft.freeze_structure()
    payload = draft.finish().model_dump()
    payload["events"] *= 2
    with pytest.raises(ValidationError, match="重复"):
        NarrativeOrganization.model_validate(payload)


def test_checked_snapshots_survive_candidate_restore_order_and_pair_orientation(draft_case):
    draft = draft_case
    ids = list(draft._declarations())
    first, second = event(draft, "first", [ids[0]]), event(draft, "second", [ids[1]])
    freeze_identities(draft, same=False)
    evidence = [OrganizationEvidence(paragraph_id=0)]
    for key, relation_type in [("cause", "causes"), ("echo", "echoes")]:
        draft.relate_events(key=key, source_kind="event", source_id=first, target_kind="event", target_id=second,
                            relation_type=relation_type, reason="原文明确比较", evidence=evidence)
    before = draft.pair_snapshot(first, second), draft.event_snapshot(first)
    draft.structure_review(source_event_id=first, target_event_id=second, disposition="related",
                           reason="已核对两项明确关联", evidence=evidence)
    draft.review_events([first, second], reason="核对完整实际版本")
    draft.freeze_structure()
    frozen = draft.structure_snapshot
    draft.events = dict(reversed(list(draft.events.items())))
    draft.relations = dict(reversed(list(draft.relations.items())))
    assert before == (draft.pair_snapshot(second, first), draft.event_snapshot(first))
    draft.freeze_structure()
    assert draft.structure_snapshot == frozen


def test_later_relation_keeps_original_review_owner_for_remaining_budget_correction(draft_case):
    from src.event_trees.organization import CandidateConflict

    draft = draft_case
    ids = list(draft._declarations())
    first, second = event(draft, "first", [ids[0]]), event(draft, "second", [ids[1]])
    freeze_identities(draft, same=False)
    draft.review_events([first, second], reason="原作者核对当前版本")
    original = draft.case_id
    draft.case_id, draft.producer_invocation_id = "later-case", "later-invocation"
    evidence = [OrganizationEvidence(paragraph_id=0)]
    draft.relate_events(key="later", source_kind="event", source_id=first, target_kind="event", target_id=second,
                        relation_type="echoes", reason="后续显式判断", evidence=evidence)
    assert draft.reviewed_events[first].source_case_id == original
    draft.structure_review(source_event_id=first, target_event_id=second, disposition="related",
                           reason="后续关系已核对", evidence=evidence)
    with pytest.raises(CandidateConflict) as raised:
        draft.freeze_structure()
    assert raised.value.case_ids == (original,)


def test_frozen_identity_cannot_change_and_stage_values_not_copied_from_model(draft_case):
    draft = draft_case
    ids = list(draft._declarations())
    identifier = event(draft, "journey", ids)
    freeze_identities(draft, same=True)
    with pytest.raises(ValueError, match="冻结"):
        event(draft, "journey", ids, progress="改写身份")
    assert identifier in draft.events
    assert not draft.revisions
