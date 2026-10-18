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
    session_id, execution_id = add_diagnosis_context(db_session, run_id)
    draft = EventOrganizationDraft(storage_for(db_session), run_id, session_id)
    draft.fixture_session = db_session
    draft.case_id = report_case_anchor(run_id)
    draft.producer_invocation_id = execution_id
    yield draft
    agent.close()


def event(draft, key, declaration_ids, **kwargs):
    return draft.identity(
        key=key,
        title=key,
        problem="待解决",
        summary=key,
        event_type="探寻",
        status="ongoing",
        declaration_ids=declaration_ids,
        stage_order=kwargs.pop("stage_order", declaration_ids),
        current_declaration_id=kwargs.pop("current_declaration_id", declaration_ids[-1]),
        reason="测试明确判断同一事件",
        evidence=[OrganizationEvidence(paragraph_id=0)],
        **kwargs,
    )["event_id"]


def submit_identities(draft, *, same):
    ids = list(draft._declarations())
    draft.review_declarations(ids, reason="已依据原文核对声明")
    draft.compare_declarations(
        source_declaration_id=ids[0],
        target_declaration_ids=[ids[1]],
        disposition="same_event" if same else "independent",
        reason="本例明确选择对应身份关系",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )


def test_bad_source_rejected_and_overlapping_identity_claim_is_first_come(draft_case):
    draft = draft_case
    ids = list(draft._declarations())
    with pytest.raises(ValueError, match="不属于"):
        event(draft, "bad", [ids[0], "missing"])
    assert not draft.events
    first = event(draft, "first", [ids[0]])
    # 工具面先到先得：重叠认领在提交时拒收，撤回后即可重新认领
    with pytest.raises(ValueError, match="认领"):
        event(draft, "second", ids)
    assert set(draft.events) == {first}
    draft.retract(
        kind="identity",
        identifier=first,
        reason="明确撤回让出完整身份候选",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    event(draft, "second", ids)
    submit_identities(draft, same=True)


def test_containment_cycle_rejected_at_submission_and_explicitly_retractable(draft_case):
    draft = draft_case
    ids = list(draft._declarations())
    child, parent = event(draft, "child", [ids[0]]), event(draft, "parent", [ids[1]])
    submit_identities(draft, same=False)
    evidence = [OrganizationEvidence(paragraph_id=0)]
    draft.contain(parent_event_id=parent, child_event_id=child, reason="独立事件组成", evidence=evidence)
    # 工具面先到先得：反向包含在提交时拒收
    with pytest.raises(ValueError, match="成环"):
        draft.contain(parent_event_id=child, child_event_id=parent, reason="反向包含候选", evidence=evidence)
    assert len(draft.containments) == 1
    draft.retract(kind="contain", identifier=f"{parent}/{child}", reason="明确撤回包含候选", evidence=evidence)
    assert draft.containments == {}
    assert draft._parents() == {}


def test_changed_source_and_duplicate_frozen_event_rejected(draft_case):
    from pydantic import ValidationError

    from src.event_trees.organization import NarrativeOrganization
    from src.storage.models import EventDeclaration

    draft = draft_case
    ids = list(draft._declarations())
    identifier = event(draft, "invalid", ids)
    # 候选提交后来源正文被改写：保存校验时来源哈希失效，不能冒充真实来源
    source = draft.fixture_session.get(EventDeclaration, ids[0])
    original_title = source.title
    source.title = "改写后的标题"
    draft.fixture_session.flush()
    submit_identities(draft, same=True)
    with pytest.raises(ValueError, match="来源"):
        draft.validate_events()
    # 撤回引用已改写来源的候选，恢复来源原文后重新提交
    draft.retract(
        kind="identity",
        identifier=identifier,
        reason="撤回引用已改写来源的候选",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    source.title = original_title
    draft.fixture_session.flush()
    identifier = event(draft, "valid", ids)
    submit_identities(draft, same=True)
    draft.review_events([identifier], reason="实际身份结构已核对")
    payload = draft.finish().model_dump()
    payload["events"] *= 2
    with pytest.raises(ValidationError, match="重复"):
        NarrativeOrganization.model_validate(payload)


def test_checked_snapshots_survive_candidate_restore_order_and_pair_orientation(draft_case):
    draft = draft_case
    ids = list(draft._declarations())
    first, second = event(draft, "first", [ids[0]]), event(draft, "second", [ids[1]])
    submit_identities(draft, same=False)
    evidence = [OrganizationEvidence(paragraph_id=0)]
    for key, relation_type in [("cause", "causes"), ("echo", "echoes")]:
        draft.relate_events(
            key=key,
            source_kind="event",
            source_id=first,
            target_kind="event",
            target_id=second,
            relation_type=relation_type,
            reason="原文明确比较",
            evidence=evidence,
        )
    before = draft.pair_snapshot(first, second), draft.event_snapshot(first)
    draft.structure_review(
        source_event_id=first,
        target_event_id=second,
        disposition="related",
        reason="已核对两项明确关联",
        evidence=evidence,
    )
    draft.review_events([first, second], reason="核对完整实际版本")
    frozen = draft.structure_digest()
    draft.events = dict(reversed(list(draft.events.items())))
    draft.relations = dict(reversed(list(draft.relations.items())))
    assert before == (draft.pair_snapshot(second, first), draft.event_snapshot(first))
    assert draft.structure_digest() == frozen


def test_repeated_identity_submission_and_stage_values_not_copied_from_model(draft_case):
    """保存前重提自己的身份候选不报错；阶段值由来源声明决定，不复制模型输入"""
    draft = draft_case
    ids = list(draft._declarations())
    identifier = event(draft, "journey", ids)
    submit_identities(draft, same=True)
    event(draft, "journey", ids, progress="改写身份")
    assert identifier in draft.events
    assert not draft.revisions
