"""外图内事件树的无数据库契约验证"""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from src.event_trees.organization import EventOrganizationDraft
from src.event_trees.organization_models import (
    BoundOrganizationEvidence,
    CompleteEventDraft,
    EventOutcomeDraft,
    EventQueueDraft,
)
from src.event_trees.queues import QueueGraph
from src.event_trees.trees import EventTrees
from src.storage.models import Base, NarrativeLink
from src.utils.event_references import referenced_event_ids


def membership(tree: str, member: str, position: int):
    return SimpleNamespace(
        tree_id=tree,
        member_event_id=member,
        position=position,
        parent_tree_id=None,
        child_tree_id=None,
    )


def evidence(event_id=None):
    return BoundOrganizationEvidence(
        chapter_id=1, paragraph_id=0, char_start=0, char_end=1, text_hash="hash", event_id=event_id
    )


def test_diamond_shares_original_tree_and_connects_tails_to_heads():
    queues = {f"t{key}": [key, key + "2"] for key in "ABCD"}
    graph = QueueGraph(
        queues,
        [("tA", "tB"), ("tA", "tC"), ("tB", "tD"), ("tC", "tD")],
        [event for members in queues.values() for event in members],
    )
    assert graph.event_parents("D") == ["B2", "C2"]
    assert graph.event_parents("D2") == ["D"]
    assert graph.event_children("A2") == ["B", "C"]
    assert graph.reachable("tA") == ["tA", "tB", "tC", "tD"]
    assert len(graph.event_tree) == 8
    assert graph.unparented == ["tA"]
    assert ("B", "C") not in [(parent, child) for parent in graph.children for child in graph.children[parent]]


def test_shared_tree_has_all_event_lines_without_duplicate_members():
    graph = QueueGraph(
        {"tA": ["A", "A2"], "tC": ["C"], "tD": ["D", "D2"]},
        [("tA", "tD"), ("tC", "tD")],
        ["A", "A2", "C", "D", "D2"],
        event_line_ids=["tA", "tC"],
    )
    assert graph.event_lines("D2") == ["tA", "tC"]
    assert graph.event_parents("D") == ["A2", "C"]


def test_empty_tree_is_valid():
    graph = QueueGraph({"t": []}, [], [])
    assert graph.queues == {"t": ()}
    assert graph.unparented == ["t"]


@pytest.mark.parametrize(
    ("queues", "references", "events"),
    [
        ({"t": ["A", "A"]}, [], ["A"]),
        ({"t1": ["A", "B"], "t2": ["B"]}, [], ["A", "B"]),
        ({"t": ["A", "missing"]}, [], ["A"]),
        ({"t": ["A"]}, [], ["A", "B"]),
        ({"t1": ["A", "B"], "t2": ["C"]}, [("B", "C")], ["A", "B", "C"]),
        ({"t": ["A"]}, [("t", "t")], ["A"]),
        ({"t1": ["A"], "t2": ["B"]}, [("t1", "t2"), ("t1", "t2")], ["A", "B"]),
        ({"t1": ["A"], "t2": ["B"]}, [("t1", "t2"), ("t2", "t1")], ["A", "B"]),
    ],
)
def test_invalid_members_or_references_are_rejected(queues, references, events):
    with pytest.raises(ValueError):
        QueueGraph(queues, references, events)


def test_saved_member_positions_are_read_in_explicit_order_and_gaps_rejected():
    rows = [membership("t", "C", 2), membership("t", "A", 0), membership("t", "B", 1)]
    assert QueueGraph.from_rows(rows, "ABC", ["t"]).queues["t"] == ("A", "B", "C")
    with pytest.raises(ValueError, match="连续"):
        QueueGraph.from_rows([rows[0], rows[1]], "AC", ["t"])


def test_final_selection_checks_selected_trees_instead_of_all_unparented():
    queues = {f"t{i}": [str(i)] for i in range(12)}
    graph = QueueGraph(queues, [], [event for members in queues.values() for event in members])
    assert len(graph.unparented) == 12
    assert graph.require_event_lines([f"t{i}" for i in range(10)])["covered_events"] == 10
    assert graph.require_event_lines([f"t{i}" for i in range(9)])["coverage"] == 0.75


def test_queue_freeze_rejects_duplicated_members_and_allows_empty_tree():
    with pytest.raises(ValidationError):
        EventQueueDraft(
            tree_id="t", title="树", description="说明", event_ids=["A", "A"], reason="原文", evidence=[evidence()]
        )
    empty = EventQueueDraft(tree_id="t", title="空树", description="等待归并")
    assert empty.event_ids == []


def test_results_keep_text_evidence_and_reject_event_contributions():
    outcome = EventOutcomeDraft(
        outcome_id="O", title="结果", description="事情结束", first_text_position=0, evidence=[evidence()]
    )
    assert outcome.evidence[0].event_id is None
    with pytest.raises(ValidationError, match="贡献来源"):
        EventOutcomeDraft(
            outcome_id="O", title="结果", description="事情结束", first_text_position=0, evidence=[evidence("A")]
        )


def test_draft_hides_other_producers_unpublished_trees(monkeypatch):
    rows = [membership("A", "A", 0)]
    session = SimpleNamespace(
        reads=SimpleNamespace(
            events=SimpleNamespace(
                list_queue_links=lambda _: rows,
                list_execution_trees=lambda _: [SimpleNamespace(group_id="A")],
            )
        ),
        narrative=SimpleNamespace(execution_ids=lambda _: [], run_events=lambda _: set()),
    )
    monkeypatch.setattr("src.event_trees.organization._run_event_dicts", lambda *_: {"A": {"event_id": "A"}})
    draft = EventOrganizationDraft(session, "run")
    draft.producer_agent_id = "reader"
    draft.events["B"] = SimpleNamespace(producer_agent_id="other", model_dump=lambda **_: {"event_id": "B"})
    draft.queues["B"] = EventQueueDraft(
        tree_id="B",
        title="树 B",
        description="其他生产者草稿",
        event_ids=["B"],
        producer_agent_id="other",
        reason="父子",
        evidence=[evidence()],
    )
    events, graph = draft.read_view()
    assert set(events) == {"A"}
    assert graph.queues == {"A": ("A",)}
    assert events["A"]["saved"] is True


def test_run_level_tree_key_rejects_creating_another_tree(monkeypatch):
    session = SimpleNamespace(
        reads=SimpleNamespace(
            events=SimpleNamespace(
                list_queue_links=lambda _: [],
                list_execution_trees=lambda _: [
                    SimpleNamespace(group_id="saved", tree_key="chenxia", producer_agent_id="earlier")
                ],
            )
        ),
        narrative=SimpleNamespace(execution_ids=lambda _: [], run_events=lambda _: set()),
    )
    monkeypatch.setattr("src.event_trees.organization._run_event_dicts", lambda *_: {})
    draft = EventOrganizationDraft(session, "run")
    draft.producer_agent_id = "later"
    with pytest.raises(ValueError, match="已被运行内事件树"):
        draft.queue(event_ids=[], tree_key="chenxia", title="重复主线")


def test_appending_to_other_execution_tree_by_key_is_rejected(monkeypatch):
    session = SimpleNamespace(
        reads=SimpleNamespace(
            events=SimpleNamespace(list_queue_links=lambda _: [], list_execution_trees=lambda _: [])
        ),
        narrative=SimpleNamespace(execution_ids=lambda _: [], run_events=lambda _: set()),
    )
    monkeypatch.setattr("src.event_trees.organization._run_event_dicts", lambda *_: {})
    draft = EventOrganizationDraft(session, "run")
    draft.producer_agent_id = "reader"
    draft.queues["T"] = EventQueueDraft(
        tree_id="T",
        title="树",
        description="其他生产者草稿",
        event_ids=[],
        tree_key="chenxia",
        producer_agent_id="other",
        reason="父子",
        evidence=[evidence()],
    )
    with pytest.raises(ValueError, match="属于其他执行"):
        draft.queue(event_ids=[], tree_key="chenxia", title="重复主线")


def test_cross_execution_tree_references_are_not_misread_as_events():
    draft = SimpleNamespace(
        events={},
        queues={},
        relations={},
        queue_references={
            "edge": SimpleNamespace(producer_agent_id="reader", parent_tree_id="tA", child_tree_id="tB", evidence=[])
        },
    )
    assert referenced_event_ids(draft, {"reader"}) == set()
    with pytest.raises(ValueError, match="完整事件树"):
        QueueGraph({"tA": ["A"]}, [("tA", "tB")], ["A"])


def test_saved_queue_cannot_change_author_or_order():
    tree = SimpleNamespace(kind="tree", producer_agent_id="first", title="树", description="说明")
    row = SimpleNamespace(member_event_id="A", producer_agent_id="first", reason="父子", position=0)
    session = SimpleNamespace(get=lambda *_: tree, scalars=lambda _: [row], flush=lambda: None)
    for author, members in (("second", ["A"]), ("first", ["A", "B"])):
        queue = SimpleNamespace(
            tree_id="t", event_ids=members, producer_agent_id=author, reason="父子",
            title="树", description="说明", tree_key=None, evidence=[],
        )
        with pytest.raises(ValueError, match="不一致"):
            from src.storage.repositories.queue_writes import save_queues

            save_queues(session, "run", [queue])


def test_rollback_preserves_formal_shared_target_and_other_authors():
    trees = EventTrees("run")
    trees.begin("saved")
    trees.nodes["A"] = {"author": "saved", "content": {}, "chapter_id": 1}
    trees.queues["tA"] = {"author": "saved", "content": {"tree_id": "tA", "event_ids": ["A"]}}
    trees.confirm("saved")
    trees.begin("working")
    trees.nodes["B"] = {"author": "working", "content": {}, "chapter_id": 1}
    trees.queues["tB"] = {"author": "working", "content": {"tree_id": "tB", "event_ids": ["B"]}}
    trees.queue_references["edge"] = {"author": "working", "content": {"parent_tree_id": "tB", "child_tree_id": "tA"}}
    before = trees.snapshot("working")
    trees.rollback("working")
    assert set(trees.nodes) == {"A"}
    assert set(trees.queues) == {"tA"}
    assert not trees.queue_references
    trees.restore(before)
    assert trees.graph("working").event_parents("A") == ["B"]


def test_schema_stays_within_thirty_tables_and_has_no_contribution_columns():
    assert len(Base.metadata.tables) == 30
    assert "member_event_id" in NarrativeLink.__table__.columns
    assert "queue_head_event_id" not in NarrativeLink.__table__.columns
    assert "outcome_group_id" not in NarrativeLink.__table__.columns
    sql = str(CreateTable(NarrativeLink.__table__).compile(dialect=postgresql.dialect()))
    assert "position >= 0" in sql
    assert "parent_tree_id <> child_tree_id" in sql


def test_annotation_reads_are_scoped_to_requester_and_formal_queues():
    trees = EventTrees("run")
    for author, tree, key in (("saved", "tA", "A"), ("reader", "tB", "B"), ("other", "tC", "C")):
        trees.begin(author)
        trees.nodes[key] = {
            "author": author,
            "chapter_id": 1,
            "content": {
                "title": key,
                "problem": "",
                "summary": "",
                "participants": [],
                "evidence_paragraph_id": 1,
                "is_foreshadow_setup": False,
            },
        }
        trees.queues[tree] = {"author": author, "content": {"tree_id": tree, "event_ids": [key]}}
    trees.confirm("saved")
    trees.queue_references["edge"] = {
        "author": "reader",
        "content": {
            "parent_tree_id": "tB",
            "child_tree_id": "tA",
        },
    }
    read = trees.read("A", author="reader")
    assert read["tree_id"] == "tA"
    assert read["event_line_ids"] == []
    assert trees.search_ids(author="reader") == ["A", "B"]
    with pytest.raises(ValueError, match="尚未保存"):
        trees.read("C", author="reader")


def test_queue_draft_can_be_retracted_and_reordered_before_save(monkeypatch):
    session = SimpleNamespace(
        reads=SimpleNamespace(
            events=SimpleNamespace(list_queue_links=lambda _: [], list_execution_trees=lambda _: [])
        ),
        narrative=SimpleNamespace(execution_ids=lambda _: [], run_events=lambda _: set()),
    )
    monkeypatch.setattr("src.event_trees.organization._run_event_dicts", lambda *_: {})
    draft = EventOrganizationDraft(session, "run")
    draft.producer_agent_id = "writer"
    for key in "AB":
        draft.events[key] = SimpleNamespace(
            producer_agent_id="writer",
            model_dump=lambda key=key, **_: {"event_id": key},
        )
    monkeypatch.setattr(draft, "read_events", lambda ids: [{"title": key, "summary": key} for key in ids])
    monkeypatch.setattr(draft, "bind_evidence", lambda _: [evidence()])
    first = draft.queue(event_ids=["A", "B"], reason="父子", evidence=[])
    draft.retract(kind="queue", identifier=first, reason="重新核对", evidence=[])
    second = draft.queue(event_ids=["B", "A"], reason="父子", evidence=[])
    assert draft.queue_graph(require_complete=True).queues == {second: ("B", "A")}


def test_appending_member_to_empty_tree_keeps_tree_reason(monkeypatch):
    session = SimpleNamespace(
        reads=SimpleNamespace(
            events=SimpleNamespace(list_queue_links=lambda _: [], list_execution_trees=lambda _: [])
        ),
        narrative=SimpleNamespace(execution_ids=lambda _: [], run_events=lambda _: set()),
    )
    monkeypatch.setattr("src.event_trees.organization._run_event_dicts", lambda *_: {})
    draft = EventOrganizationDraft(session, "run")
    draft.producer_agent_id = "writer"
    draft.events["A"] = SimpleNamespace(
        producer_agent_id="writer",
        model_dump=lambda **_: {"event_id": "A"},
    )
    monkeypatch.setattr(draft, "read_events", lambda ids: [{"title": key, "summary": key} for key in ids])
    monkeypatch.setattr(draft, "bind_evidence", lambda _: [evidence()])
    tree_id = draft.queue(event_ids=[], tree_key="saga", title="主线")
    draft.queue(event_ids=["A"], tree_id=tree_id, reason="以原文锚点为总纲")
    stored = draft.queues[tree_id]
    assert stored.reason == "以原文锚点为总纲"
    assert EventQueueDraft.model_validate(stored.model_dump()).reason == "以原文锚点为总纲"


def test_last_case_checks_submitted_producers_together_and_keeps_claim_correctable():
    from src.agents.diagnosis.tools import _validate_case_submission
    from src.storage.records.cases import event_tree_case_description

    tree_ids = {key: f"t{key}" for key in "ABCD"}
    graph = QueueGraph(
        {"tParent": ["P"], **{tree_id: [key] for key, tree_id in tree_ids.items()}},
        [("tParent", tree_id) for tree_id in tree_ids.values()],
        ["P", *"ABCD"],
    )
    draft = SimpleNamespace(queue_graph=Mock(return_value=graph))
    pool = SimpleNamespace(
        unsubmitted_for=lambda _: ["last"],
        case_runtime={"done": {"submitted": True, "owner": "first"}, "last": {"submitted": False, "owner": "second"}},
        cases={
            key: {"case_type": "event", "description": event_tree_case_description(tree_ids[key])}
            for key in "ABCD"
        },
    )
    _validate_case_submission(pool, draft, "second", "last")
    assert draft.queue_graph.call_args.kwargs["producers"] == {"first", "second"}
    assert pool.case_runtime["last"]["submitted"] is False
    pool.cases.pop("D")
    _validate_case_submission(pool, draft, "second", "last")


def test_committed_session_is_protected_from_abort_even_if_recovery_fails():
    from src.agents.diagnosis.domain import DiagnosisDomain

    domain = object.__new__(DiagnosisDomain)
    domain.lock = threading.RLock()
    domain.draft = SimpleNamespace(publication_lock=threading.RLock())
    domain.session_saved = set()
    domain.session_committed = {"writer"}
    domain.case_pool = SimpleNamespace(abandon=Mock())
    domain.abort_session("writer")
    domain.case_pool.abandon.assert_not_called()


def test_report_commit_callback_precedes_failing_memory_confirmation(monkeypatch):
    from src.agents.diagnosis import persistence
    from src.diagnosis.schema import AgentAnalysis
    from src.event_trees.organization_models import NarrativeOrganization

    organization = NarrativeOrganization.model_construct(source_agent_id="reporter")
    analysis = AgentAnalysis(narrative_organization=organization)
    monkeypatch.setattr(persistence, "_existing_report", lambda *_: None)
    monkeypatch.setattr("src.event_trees.organization.validate_organization", lambda *_: None)
    monkeypatch.setattr(persistence, "character_entity_ids", lambda *_: {})
    committed = Mock()
    storage = SimpleNamespace(
        diagnosis=SimpleNamespace(
            save_report=Mock(
                return_value={
                    "warnings": [],
                    "warnings_by_author": {"writer": []},
                }
            )
        )
    )
    pool = SimpleNamespace(
        executions={"writer"},
        contribution=lambda _: {},
        save_warnings={},
        confirm=Mock(side_effect=RuntimeError("confirm failed")),
    )
    with pytest.raises(RuntimeError, match="confirm failed"):
        persistence.save_diagnosis_result(storage, "run", analysis, case_pool=pool, on_committed=committed)
    storage.diagnosis.save_report.assert_called_once()
    committed.assert_called_once()


def test_report_domain_recovers_committed_analysis_after_confirmation_failure(monkeypatch):
    from src.agents.diagnosis import domain as module
    from src.diagnosis.schema import AgentAnalysis
    from src.event_trees.organization_models import NarrativeOrganization

    domain = object.__new__(module.DiagnosisDomain)
    domain._require_cases_saved = lambda: None
    domain._report_snapshot = lambda: "snapshot"
    domain.reports = {"anchor": {"analysis": {"diagnosis": "报告"}}}
    domain.report_bindings = {"anchor": "snapshot"}
    domain.draft = SimpleNamespace(finish=lambda: NarrativeOrganization.model_construct(source_agent_id="reporter"))
    domain.session = object()
    domain.run_id, domain.novel_id = "run", "novel"
    domain.session_committed, domain.session_saved = set(), set()
    domain.case_pool, domain.case_writers = object(), {}
    domain._case_graph = lambda: None
    domain._case_dialogue_candidates = lambda: []
    domain._recover_committed_session = Mock()
    monkeypatch.setattr(
        module, "DiagnosisQueries", lambda _: SimpleNamespace(calculate_foreshadow_expectation=lambda _: 0)
    )

    def save(*args, on_committed, **kwargs):
        on_committed()
        raise RuntimeError("confirm failed")

    monkeypatch.setattr(module, "save_diagnosis_result", save)
    domain._save_report_progress("reporter")
    assert isinstance(domain._analysis, AgentAnalysis)
    assert domain._analysis.diagnosis == "报告"
    assert domain.session_committed == {"reporter"}
    domain._recover_committed_session.assert_called_once_with("reporter")


def test_independent_save_validation_checks_all_snapshot_producers(monkeypatch):
    from src.event_trees.organization import validate_organization
    from src.event_trees.organization_models import CompleteEventDraft, NarrativeOrganization

    storage = SimpleNamespace(
        reads=SimpleNamespace(
            events=SimpleNamespace(list_queue_links=lambda _: [], list_execution_trees=lambda _: [])
        ),
        narrative=SimpleNamespace(execution_ids=lambda _: [], run_events=lambda _: set()),
    )
    monkeypatch.setattr("src.event_trees.organization._run_event_dicts", lambda *_: {})
    monkeypatch.setattr("src.event_trees.organization_rules._run_events", lambda *_: {})
    events = [
        CompleteEventDraft(
            event_id=key,
            local_key=key,
            title=key,
            problem=key,
            summary=key,
            event_type="行动",
            status="ongoing",
            from_chapter_id=1,
            to_chapter_id=1,
            first_text_position=0,
            producer_agent_id=key,
            evidence=[evidence()],
        )
        for key in "AB"
    ]
    queues = [
        EventQueueDraft(
            tree_id=f"t{key}", title=key, description=key, event_ids=members,
            reason="父子", producer_agent_id=key, evidence=[evidence()],
        )
        for key, members in (("A", ["A", "B"]), ("B", ["B"]))
    ]
    snapshot = NarrativeOrganization(events=events, queues=queues)
    with pytest.raises(ValueError, match="事件只能属于一棵"):
        validate_organization(storage, "run", snapshot)


def test_foreshadowing_root_and_payoff_must_pair() -> None:
    """伏笔根必须有回收预期，非伏笔根不得携带回收预期"""
    base = {
        "event_id": "e1",
        "local_key": "k1",
        "title": "埋设",
        "problem": "是否埋下",
        "summary": "埋设",
        "event_type": "行动",
        "status": "ongoing",
        "from_chapter_id": 1,
        "to_chapter_id": 1,
        "first_text_position": 0,
        "evidence": [evidence()],
    }
    with pytest.raises(ValidationError, match="必须成对"):
        CompleteEventDraft(**base, is_foreshadowing_root=True)
    with pytest.raises(ValidationError, match="必须成对"):
        CompleteEventDraft(**base, payoff_likelihood="high")
    CompleteEventDraft(**base, is_foreshadowing_root=True, payoff_likelihood="high")


def test_more_than_ten_unparented_trees_do_not_block_structural_merging() -> None:
    queues = {f"t{index}": (f"q{index}",) for index in range(11)}
    graph = QueueGraph(queues, [], [f"q{index}" for index in range(11)])
    assert len(graph.unparented) == 11
    assert graph.require_event_lines([f"t{index}" for index in range(9)])["coverage"] == 9 / 11


def test_selected_tree_keeps_descendants_and_counts_shared_events_once():
    graph = QueueGraph(
        {"tA": ["a0", "a1"], **{f"t{key}": [key] for key in "bcdef"}},
        [("tA", "tb"), ("tA", "tc"), ("tb", "td"), ("tc", "td")],
        ["a0", "a1", *"bcdef"],
    )
    assert graph.tree_events("tA") == ["a0", "a1", "b", "c", "d"]
    coverage = graph.require_event_lines(["tA", "tb", "tc", "te", "tf"])
    assert coverage == {"covered_events": 7, "total_events": 7, "coverage": 1.0}


@pytest.mark.parametrize("selected", [["t0"] * 5, [f"t{i}" for i in range(4)], [f"t{i}" for i in range(11)]])
def test_event_line_selection_rejects_duplicates_and_invalid_counts(selected):
    graph = QueueGraph({f"t{i}": [str(i)] for i in range(11)}, [], map(str, range(11)))
    with pytest.raises(ValueError, match="5–10"):
        graph.require_event_lines(selected)
