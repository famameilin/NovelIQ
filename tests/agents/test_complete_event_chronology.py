"""阶段链由明确声明顺序决定，不按章节或最后写入推定（2026-10-16 全库 3NF 改造）

阶段即 event_revisions 的显式 stage_index 链：序号从 0 连续、前驱为 index−1、
正文与参与者从绑定声明读回，不由时间或章号推断。
"""

import pytest
from sqlalchemy import select

from src.event_trees import storage_map as smap
from src.event_trees.read.organization import EventTreeQuery
from src.storage.models import EventRevision
from tests.agents.test_complete_event_invariants import draft_case as draft_case
from tests.agents.test_complete_event_invariants import event, freeze_identities
from tests.support.event_tree_fixtures import close_structure


def _publish(session, draft) -> str:
    """按正式发布入口保存已冻结草稿，返回唯一事件身份"""
    from tests.support.event_tree_fixtures import publish_draft

    assert len(draft.events) == 1
    close_structure(session, draft, evidence_paragraph_id=0)
    mapping = publish_draft(session, draft.run_id, draft)
    return next(iter(mapping.values()))


def test_stage_order_keeps_actual_source_values_and_rejects_incomplete_order(draft_case):
    draft = draft_case
    ids = list(draft._declarations())
    with pytest.raises(ValueError, match="stage_order"):
        event(draft, "bad", ids, stage_order=[ids[0]])
    chosen_order = list(reversed(ids))
    event(draft, "journey", ids, stage_order=chosen_order, current_declaration_id=chosen_order[-1])
    freeze_identities(draft, same=True)
    event_id = _publish(draft.session, draft)
    stages = list(
        draft.session.scalars(
            select(EventRevision)
            .where(EventRevision.event_id == event_id)
            .order_by(EventRevision.stage_index)
        )
    )
    by_source = {stage.declaration_id: stage for stage in stages}
    assert [stage.stage_index for stage in stages] == [0, 1]
    assert by_source[chosen_order[0]].stage_index == 0
    assert by_source[chosen_order[1]].stage_index == 1
    # 阶段链从 0 连续，前驱与正文/参与者都是读取投影
    query = EventTreeQuery(draft.session, draft.run_id)
    query.fetch()
    first = query.revisions[by_source[chosen_order[0]].revision_id]
    second = query.revisions[by_source[chosen_order[1]].revision_id]
    assert first.previous_revision_id is None
    assert second.previous_revision_id == first.revision_id
    for identifier, stage in ((chosen_order[0], first), (chosen_order[1], second)):
        source = draft._declarations()[identifier]
        assert stage.summary == source["summary"]
        assert stage.participants == source["participants"]
        assert stage.event_type == source["event_type"]
    assert draft.session.scalar(
        select(EventRevision.declaration_id).where(EventRevision.revision_id == first.revision_id)
    ) == chosen_order[0]
    assert smap.stage_chain(draft.session, [event_id])[event_id][-1].revision_id == second.revision_id
