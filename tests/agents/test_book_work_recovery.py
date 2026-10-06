"""实际保存引用与单作者确认恢复的不变量"""

from copy import deepcopy
from types import SimpleNamespace

from src.agents.annotation.schema import BoundEvent, EntityInput
from src.case_pool import CasePool
from src.event_trees.trees import EventTrees
from src.fact_graph.graph import FactGraph, mention_uuid


def test_saved_reference_restores_endpoints_without_fabricating_entity_writes():
    graph = FactGraph(run_scope="run")
    references = [
        {"entity_id": mention_uuid("run", 2, name), "name": name, "entity_type": "character"}
        for name in ("Alice", "Bob")
    ]
    graph.restore_work(
        "saved-b", "b1", 2, "solo", [],
        [{"from_entity": "Alice", "to_entity": "Bob", "relation_type": "同一人物", "chapter_id": 2}],
        references,
    )
    assert graph.entity_id("Alice") == references[0]["entity_id"]
    assert graph.resolve_entity_id(references[1]["entity_id"], label="target") == "Bob"
    assert graph.drain_ops("saved-b", "b1")["entity_ops"] == []
    assert len(graph.active_relations) == 1


def test_legacy_identity_and_event_facts_are_not_current_work_operations():
    reference = SimpleNamespace(
        fact_type="entity_reference", content={"operation_order": 0},
        value={"entity_id": mention_uuid("run", 1, "Alice"), "name": "Alice", "entity_type": "character"},
    )
    facts = [SimpleNamespace(fact_type=kind, content={}, value={}) for kind in ("identity", "event")]
    facts.append(reference)
    record = SimpleNamespace(output_id="actual", work_id="saved", invocation_id="s1",
                             actual_input={"chapter_sequence": 1}, role="solo")

    class SavedSession:
        def get(self, model, identifier):
            return record

        def execute(self, statement):
            return SimpleNamespace(scalars=lambda: facts)

    graph = FactGraph(run_scope="run")
    graph.restore_storage(SavedSession(), [record])
    snapshot = graph.load_saved_work(SavedSession(), "saved", "s1", "actual")
    graph.recover_work(snapshot)
    assert graph.entity_id("Alice") == reference.value["entity_id"]
    assert graph.drain_ops("saved", "s1") == {"entity_ops": [], "relation_assert_ops": []}


def test_single_work_fact_recovery_preserves_other_inflight_contribution():
    graph = FactGraph(run_scope="run")
    graph.begin("other", "o1", 3, "structure")
    with graph.author("other", "o1"):
        entity = EntityInput(name="Other", entity_type="character", attributes={"current": True})
        graph.register_entities([entity])
        graph.record_entity_ops([entity], chapter_id=3)
    other = deepcopy(graph.contributions[("other", "o1")])
    snapshot = {
        "author": ("saved", "s1"), "sequence": 1, "role": "solo", "entity_ops": [],
        "relation_assert_ops": [], "entity_references": [
            {"entity_id": mention_uuid("run", 1, "Saved"), "name": "Saved", "entity_type": "character"}
        ],
    }
    graph.recover_work(snapshot)
    graph.recover_work(snapshot)
    assert graph.contributions[("other", "o1")] == other
    assert graph.entity_attributes["other"] == {"current": True}
    assert graph.entity_id("Saved") is not None


def test_saved_reference_survives_source_rollback_in_current_run():
    graph = FactGraph(run_scope="run")
    graph.begin("source", "a1", 1, "structure")
    graph.begin("saved", "b1", 2, "solo")
    with graph.author("source", "a1"):
        entity = EntityInput(name="Alice", entity_type="character", attributes={"source_only": True})
        graph.register_entities([entity])
        graph.record_entity_ops([entity], chapter_id=1)
    identifier = graph.entity_id("Alice")
    graph.reference_entities(("saved", "b1"), [
        {"entity_id": identifier, "name": "Alice", "entity_type": "character"}
    ])
    graph.confirm("saved", "b1")
    graph.rollback("source", "a1")
    assert graph.resolve_entity_id(identifier, label="actual reference") == "Alice"
    assert graph.entity_attributes["alice"] == {}
    assert graph.drain_ops("saved", "b1")["entity_ops"] == []


def test_single_work_tree_recovery_preserves_other_inflight_nodes():
    trees = EventTrees("run")
    trees.begin("other", "o1")
    other = BoundEvent(
        node_id="other-node", tree_id="other-tree", parent_node_id=None, cause_role="root",
        description="Other", evidence_paragraph_id=3,
    )
    trees.sync(("other", "o1"), 3, [other])
    saved = other.model_copy(update={"node_id": "saved-node", "tree_id": "saved-tree"})
    snapshot = {
        "author": ("saved", "s1"), "nodes": {
            "saved-node": {"author": ("saved", "s1"), "chapter_id": 1, "content": saved.model_dump(mode="json")}
        }, "connections": {},
    }
    trees.recover_work(snapshot)
    trees.recover_work(snapshot)
    assert trees.read("other-node")["saved"] is False
    assert trees.read("saved-node")["saved"] is True
    assert ("other", "o1") in trees.executions


def test_single_work_case_recovery_restores_own_exclusion_and_preserves_other_owner():
    pool = CasePool("run")
    saved, other = ("saved", "s1"), ("other", "o1")
    pool.begin(*saved)
    pool.begin(*other)
    own = pool.push("Own case", saved)
    external = pool.push("Other case", other)
    pool.promise(own["case_id"], saved)
    pool.deliver(
        {"case_id": own["case_id"], "state": "resolved", "reason": "Actually checked"}, saved,
        call_id="finished", connections=[], reads=[{"paragraph_id": 1}],
    )
    pool.promise(external["case_id"], other)
    snapshot = {
        "author": saved, "registrations": {own["case_id"]: own}, "deliveries": deepcopy(pool.deliveries[saved]),
    }
    pool.confirm(*saved)
    pool.recover_work(snapshot)
    pool.recover_work(snapshot)
    assert pool.case_runtime[own["case_id"]]["owner"] == saved
    assert pool.case_runtime[external["case_id"]]["owner"] == other
    assert pool.case_runtime[external["case_id"]]["active"] is True
    assert len(pool.deliveries[saved]) == 1
    pool.confirm(*saved)
    assert pool.case_runtime[own["case_id"]]["owner"] is None


def test_full_case_restore_is_idempotent_and_forgets_discarded_contributions():
    pool = CasePool("run")
    deferred = {"case_id": "case", "state": "deferred", "call_id": "a", "accepted_order": 1,
                "connections": [], "reads": [], "reason": "More context needed"}
    resolved = {**deferred, "state": "resolved", "call_id": "b", "accepted_order": 2,
                "reads": [{"paragraph_id": 2}], "reason": "Actually checked"}
    case = SimpleNamespace(case_id="case", description="Actual case", state="resolved", contributions={
        "a": {"invocation_id": "a1", "deliveries": [deferred]},
        "b": {"invocation_id": "b1", "deliveries": [resolved]},
    })
    class Result:
        def __init__(self, values):
            self.values = values

        def scalars(self):
            return self

        def all(self):
            return self.values

        def __iter__(self):
            return iter(self.values)

    class ReadSession:
        def execute(self, statement):
            return Result([] if "event_edges" in str(statement) else [case])

        def flush(self):
            pass

    session = ReadSession()
    pool.restore_storage(session, set())
    pool.restore_storage(session, set())
    assert len(pool.deliveries[("b", "b1")]) == 1
    pool.restore_storage(session, {"b"})
    assert ("b", "b1") not in pool.deliveries and ("b", "b1") not in pool.saved
    assert pool.search()[0]["state"] == "deferred"
    pool.begin("later", "l1")
    pool.rollback("later", "l1")
    assert pool.search()[0]["state"] == "deferred"
