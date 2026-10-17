"""实际保存引用与单作者确认恢复的不变量"""

from copy import deepcopy
from types import SimpleNamespace

from src.case_pool import CasePool
from src.event_trees.models import BoundEvent
from src.event_trees.trees import EventTrees
from src.fact_graph.graph import FactGraph, entity_key, mention_uuid
from src.fact_graph.inputs import EntityInput


def test_saved_reference_restores_endpoints_without_fabricating_entity_writes():
    graph = FactGraph(run_scope="run")
    references = [
        {"entity_id": mention_uuid("run", 2, name, "character"), "name": name, "entity_type": "character"}
        for name in ("Alice", "Bob")
    ]
    graph.restore_work(
        "saved-b",
        "b1",
        2,
        "solo",
        [],
        [
            {
                "from_entity": entity_key("Alice", "character"),
                "to_entity": entity_key("Bob", "character"),
                "relation_type": "同一人物",
                "chapter_id": 2,
            }
        ],
        references,
    )
    assert graph.entity_id("Alice", "character") == references[0]["entity_id"]
    resolved = graph.resolve_entity_id(references[1]["entity_id"], label="target")
    assert graph.display_name(resolved) == "Bob"
    assert graph.drain_ops("saved-b", "b1")["entity_ops"] == []
    assert len(graph.active_relations) == 1


def test_legacy_identity_and_event_facts_are_not_current_work_operations(db_session):
    """2026-10-16 3NF：从存储读回 work 只恢复当前形状的图操作

    已登记实体在后续章只作为引用支持（旧 identity/event 事实类型已退场）：读回该 work
    后不产生实体操作与关系操作，引用端点仍可解析。
    """
    from uuid import uuid4

    from src.agents.annotation.output_models import BoundChapterAnnotation
    from src.fact_graph.inputs import ChapterMetricsInput
    from src.storage.models import ChapterAnnotation, Execution, Paragraph
    from tests.support.chapter_annotation_helpers import (
        character_fact,
        commit_test_annotation,
        create_run_with_chunks,
        make_bound_event,
        persist_chapter_annotation,
    )

    _novel_id, run_id = create_run_with_chunks(
        db_session, texts=["Alice 出场。", "Alice 在场。"], chapter_ids=[1, 2]
    )
    persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
        characters=[character_fact(chapter_id=1, name="Alice", action="出场")],
    )
    paragraph = db_session.query(Paragraph).filter_by(run_id=run_id, chapter_id=2).one()
    output = BoundChapterAnnotation(
        metrics=ChapterMetricsInput(summary="本章事件", emotional_valence=0, narrative_function="冲突"),
        events=[
            make_bound_event(
                description="Alice 在场",
                participants=[{"entity": "Alice", "role": "主体"}],
                node_id=str(uuid4()),
                tree_id=str(uuid4()),
                evidence_paragraph_id=paragraph.paragraph_id,
            )
        ],
        dialogues=[],
        character_observations=[],
    )
    record_id = commit_test_annotation(db_session, run_id=run_id, chapter_id=2, annotation=output)
    record = db_session.get(ChapterAnnotation, record_id)
    work_id = str(db_session.get(Execution, record.execution_id).work_id)
    graph = FactGraph(run_scope=run_id)
    graph.restore_storage(
        db_session,
        [
            SimpleNamespace(
                execution_id=record.execution_id, work_id=work_id, chapter_id=2, sequence=2, role="solo"
            )
        ],
    )
    snapshot = graph.load_saved_work(db_session, work_id, record.execution_id, record_id)
    graph.recover_work(snapshot)
    assert graph.entity_id("Alice", "character") == mention_uuid(run_id, 1, "Alice", "character")
    assert graph.drain_ops(work_id, record.execution_id) == {"entity_ops": [], "relation_assert_ops": []}


def test_single_work_fact_recovery_preserves_other_inflight_contribution():
    graph = FactGraph(run_scope="run")
    graph.begin("other", "o1", 3, "structure")
    with graph.author("other", "o1"):
        entity = EntityInput(name="Other", entity_type="character", description="在飞实体")
        graph.register_entities([entity])
        graph.record_entity_ops([entity], chapter_id=3)
    other = deepcopy(graph.contributions[("other", "o1")])
    snapshot = {
        "author": ("saved", "s1"),
        "sequence": 1,
        "role": "solo",
        "entity_ops": [],
        "relation_assert_ops": [],
        "entity_references": [
            {"entity_id": mention_uuid("run", 1, "Saved", "character"), "name": "Saved", "entity_type": "character"}
        ],
    }
    graph.recover_work(snapshot)
    graph.recover_work(snapshot)
    assert graph.contributions[("other", "o1")] == other
    assert graph.entity_attributes[entity_key("Other", "character")] == {"description": "在飞实体"}
    assert graph.entity_id("Saved", "character") is not None


def test_saved_reference_survives_source_rollback_in_current_run():
    graph = FactGraph(run_scope="run")
    graph.begin("source", "a1", 1, "structure")
    graph.begin("saved", "b1", 2, "solo")
    with graph.author("source", "a1"):
        entity = EntityInput(name="Alice", entity_type="character", description="来源章专属")
        graph.register_entities([entity])
        graph.record_entity_ops([entity], chapter_id=1)
    identifier = graph.entity_id("Alice", "character")
    graph.reference_entities(("saved", "b1"), [{"entity_id": identifier, "name": "Alice", "entity_type": "character"}])
    graph.confirm("saved", "b1")
    graph.rollback("source", "a1")
    assert graph.display_name(graph.resolve_entity_id(identifier, label="actual reference")) == "Alice"
    # 回滚的源章不留下实体状态（只有保留侧的引用支持）
    assert graph.entity_attributes.get(entity_key("Alice", "character"), {}) == {}
    assert graph.drain_ops("saved", "b1")["entity_ops"] == []


def test_single_work_tree_recovery_preserves_other_inflight_nodes():
    trees = EventTrees("run")
    trees.begin("other", "o1")
    other = BoundEvent(
        node_id="other-node",
        tree_id="other-tree",
        parent_node_id=None,
        cause_role="root",
        description="Other",
        evidence_paragraph_id=3,
        title="Other",
        problem="明确事件问题",
        summary="Other",
        event_type="行动",
        status="ongoing",
        declaration_id="other-node",
    )
    trees.sync(("other", "o1"), 3, [other])
    saved = other.model_copy(update={"node_id": "saved-node", "tree_id": "saved-tree"})
    snapshot = {
        "author": ("saved", "s1"),
        "nodes": {"saved-node": {"author": ("saved", "s1"), "chapter_id": 1, "content": saved.model_dump(mode="json")}},
        "connections": {},
        "actions": {},
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
    own = pool.push("character", "Own case", saved)
    external = pool.push("character", "Other case", other)
    pool.promise(own["case_id"], saved)
    pool.associate(
        own["case_id"],
        saved,
        tool_name="write_event",
        call_id="write",
        receipt={"status": "written", "record": "process"},
        is_write=True,
    )

    pool.promise(external["case_id"], other)
    snapshot = {
        "author": saved,
        "registrations": {own["case_id"]: own},
        "deliveries": deepcopy(pool.deliveries[saved]),
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


def test_full_case_restore_is_idempotent_and_forgets_discarded_contributions(db_session):
    """真实存储重载：重复恢复幂等，废弃 work 的支持与交付整体退场"""
    import json
    from uuid import uuid4

    from src.case_pool.contributions import CaseContribution
    from src.storage.models import Execution, WorkItem
    from src.storage.models.base import naive_utcnow
    from tests.support.chapter_annotation_helpers import create_run_with_chunks

    _novel, run_id = create_run_with_chunks(db_session, texts=["原文一。", "原文二。"], chapter_ids=[1, 2])
    # work 身份在库内全局唯一（work_items 主键即 work_id），用例内自取名避免跨用例碰撞
    suffix = uuid4().hex[:8]
    a = (f"a-{suffix}", f"a1-{suffix}")
    b = (f"b-{suffix}", f"b1-{suffix}")
    for author, chapter_id in ((a, 1), (b, 2)):
        db_session.add(
            WorkItem(
                work_id=author[0], role="solo", annotation_run_id=run_id, annotation_chapter_id=chapter_id
            )
        )
    db_session.flush()
    for author in (a, b):
        db_session.add(
            Execution(
                execution_id=author[1], work_id=author[0], attempt_number=1,
                started_at=naive_utcnow(), status="success",
            )
        )
    db_session.flush()
    pool = CasePool(run_id)
    pool.begin(*a)
    pool.begin(*b)
    case = pool.push("character", "Actual case", a)
    pool.promise(case["case_id"], a)
    assert pool.associate(
        case["case_id"], a, tool_name="read_event", call_id="a", receipt={}, is_write=False
    )["status"] == "success"
    pool.stop(a)
    pool.promise(case["case_id"], b)
    assert pool.associate(
        case["case_id"], b, tool_name="write_event", call_id="b", receipt={}, is_write=True
    )["status"] == "success"

    def contribution(author):
        snapshot = {
            "created_case_ids": sorted(pool.created.get(author, set())),
            "registrations": {key: pool.cases[key] for key in pool.registrations[author]},
            "deliveries": pool.deliveries[author],
        }
        return CaseContribution(run_id, author[0], author[1], json.dumps(snapshot, ensure_ascii=False))

    assert pool.save_work(db_session, contribution(a)) == []
    assert pool.save_work(db_session, contribution(b)) == []
    db_session.flush()

    restored = CasePool(run_id)
    restored.restore_storage(db_session, set())
    restored.restore_storage(db_session, set())
    assert len(restored.deliveries[b]) == 1 and len(restored.deliveries[a]) == 1
    assert restored.case_runtime[case["case_id"]]["state"] == "resolved"
    restored.restore_storage(db_session, {b[0]})
    assert b not in restored.deliveries and b not in restored.saved
    assert restored.search()[0]["state"] == "pending"
    restored.begin("later", "l1")
    restored.rollback("later", "l1")
    assert restored.search()[0]["state"] == "pending"
