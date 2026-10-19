"""章节声明保留自身正文，全书事件独立保存与恢复"""

from sqlalchemy import select

from src.event_trees.diagnosis_persistence import hydrate_draft_from_run
from src.event_trees.organization import EventOrganizationDraft
from src.event_trees.read.forest import EventForestQuery
from src.event_trees.read.organization import EventTreeQuery
from src.storage.models import EventDeclarationBinding
from tests.agents.test_complete_event_invariants import draft_case as draft_case
from tests.agents.test_complete_event_invariants import event, submit_identities
from tests.support.event_tree_fixtures import close_structure, publish_draft
from tests.support.storage_fixtures import storage_for


def test_same_chapter_sources_keep_all_bindings_and_own_body_after_restore(draft_case):
    draft = draft_case
    declarations = draft._declarations()
    ids = list(declarations)
    identifier = event(draft, "全书旅程概要", list(reversed(ids)))
    submit_identities(draft, same=True)
    close_structure(draft.fixture_session, draft, evidence_paragraph_id=0)
    publish_draft(draft.fixture_session, draft.run_id, draft)
    bindings = list(draft.fixture_session.scalars(select(EventDeclarationBinding).where(
        EventDeclarationBinding.event_id == identifier
    )))
    assert {row.declaration_id for row in bindings} == set(ids)
    assert len(bindings) == 2
    storage = storage_for(draft.fixture_session)
    query = EventTreeQuery(storage, draft.run_id)
    assert query.detail(identifier)["summary"] == "全书旅程概要"
    for source_id, source in declarations.items():
        detail = query.chapter_detail(source["chapter_id"], source_id)
        assert detail["summary"] == source["summary"]
        assert detail["event_id"] == identifier
        assert detail["declaration_id"] == source_id
    snapshot = EventForestQuery(storage).fetch_snapshot(draft.run_id, chapter_id=1)
    assert {row.declaration_id for row in snapshot.event_nodes} == set(ids)
    assert {row.event_id for row in snapshot.event_nodes} == {identifier}
    restored = EventOrganizationDraft(storage, draft.run_id, draft.agent_id)
    hydrate_draft_from_run(storage, draft.run_id, restored)
    saved = restored.events[identifier]
    assert saved.summary == "全书旅程概要"
    assert set(saved.declaration_ids) == set(ids)
    assert saved.producer_agent_id == draft.events[identifier].producer_agent_id
    assert not hasattr(restored, "revisions")
