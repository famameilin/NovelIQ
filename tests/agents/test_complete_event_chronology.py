"事件正文与章节投影保持独立"

from src.event_trees.diagnosis_persistence import hydrate_draft_from_run
from src.event_trees.organization import EventOrganizationDraft
from src.event_trees.read.organization import EventTreeQuery
from tests.agents.test_complete_event_invariants import draft_case as draft_case
from tests.agents.test_complete_event_invariants import event
from tests.support.event_tree_fixtures import publish_draft
from tests.support.storage_fixtures import storage_for


def test_saved_children_keep_own_content_after_parent_and_restore(draft_case):
    draft = draft_case
    sources = draft._all_events()
    parent = event(draft, "整体旅程", list(sources))
    publish_draft(draft.fixture_session, draft.run_id, draft)
    storage = storage_for(draft.fixture_session)
    query = EventTreeQuery(storage, draft.run_id)
    assert query.detail(parent)["summary"] == "整体旅程"
    assert len(query.detail(parent)["direct_children"]) == 2
    for identifier, source in sources.items():
        assert query.chapter_detail(1, identifier)["summary"] == source["summary"]
    restored = EventOrganizationDraft(storage, draft.run_id, draft.agent_id)
    hydrate_draft_from_run(storage, draft.run_id, restored)
    assert set(restored.events) == set(sources) | {parent}
