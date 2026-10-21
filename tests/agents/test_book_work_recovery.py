"""实际保存引用与单作者确认恢复的不变量"""

from copy import deepcopy
from types import SimpleNamespace

from src.case_pool import CasePool
from src.event_trees.models import BoundEvent
from src.event_trees.trees import EventTrees
from src.fact_graph.graph import FactGraph, entity_key
from src.fact_graph.inputs import EntityInput
from src.storage import new_id
from tests.support.storage_fixtures import fixture_id, mention_id, storage_for


def test_saved_reference_restores_endpoints_without_fabricating_entity_writes():
    graph = FactGraph(run_scope="run")
    references = [
        {"entity_id": mention_id("run", 2, name, "character"), "name": name, "entity_type": "character"}
        for name in ("Alice", "Bob")
    ]
    graph.restore_work(
        fixture_id(__name__, "b1"),
        2,
        "annotation",
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
    assert graph.drain_ops(fixture_id(__name__, "b1"))["entity_ops"] == []
    assert len(graph.active_relations) == 1


def test_legacy_identity_and_event_facts_are_not_current_work_operations(db_session):
    """从存储读回执行只恢复当前形状的图操作

    已登记实体在后续章只作为引用支持：读回该执行后不产生实体操作与关系操作，
    引用端点仍可解析。
    """

    from src.agents.annotation.output_models import BoundChapterAnnotation
    from src.fact_graph.inputs import ChapterMetricsInput
    from src.storage.models import ChapterAnnotation, Paragraph
    from tests.support.chapter_annotation_helpers import (
        character_fact,
        commit_test_annotation,
        create_run_with_chunks,
        make_bound_event,
        persist_chapter_annotation,
    )

    _novel_id, run_id = create_run_with_chunks(db_session, texts=["Alice 出场。", "Alice 在场。"], chapter_ids=[1, 2])
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
                node_id=new_id(),
                tree_id=new_id(),
                evidence_paragraph_id=paragraph.paragraph_id,
            )
        ],
        dialogues=[],
        character_observations=[],
    )
    record_id = commit_test_annotation(db_session, run_id=run_id, chapter_id=2, annotation=output)
    record = db_session.get(ChapterAnnotation, record_id)
    author = str(record.agent_id)
    graph = FactGraph(run_scope=run_id)
    graph.restore_storage(
        storage_for(db_session),
        [SimpleNamespace(agent_id=author, record_id=record_id, chapter_id=2, sequence=2, role="annotation")],
    )
    snapshot = graph.load_saved_work(storage_for(db_session), author, record_id)
    graph.recover_work(snapshot)
    from sqlalchemy import select

    from src.storage.models import GraphEntity

    assert graph.entity_id("Alice", "character") == db_session.scalar(
        select(GraphEntity.entity_id).where(GraphEntity.run_id == run_id, GraphEntity.canonical_name == "Alice")
    )
    assert graph.drain_ops(author) == {"entity_ops": [], "relation_assert_ops": []}


def test_single_work_fact_recovery_preserves_other_inflight_contribution():
    graph = FactGraph(run_scope="run")
    graph.begin(fixture_id(__name__, "o1"), 3, "entity")
    with graph.author(fixture_id(__name__, "o1")):
        entity = EntityInput(name="Other", entity_type="character", description="在飞实体")
        graph.register_entities([entity])
        graph.record_entity_ops([entity], chapter_id=3)
    other = deepcopy(graph.contributions[fixture_id(__name__, "o1")])
    snapshot = {
        "author": fixture_id(__name__, "s1"),
        "sequence": 1,
        "role": "annotation",
        "entity_ops": [],
        "relation_assert_ops": [],
        "entity_references": [
            {"entity_id": mention_id("run", 1, "Saved", "character"), "name": "Saved", "entity_type": "character"}
        ],
    }
    graph.recover_work(snapshot)
    graph.recover_work(snapshot)
    assert graph.contributions[fixture_id(__name__, "o1")] == other
    assert graph.entity_attributes[entity_key("Other", "character")] == {"description": "在飞实体"}
    assert graph.entity_id("Saved", "character") is not None


def test_saved_reference_survives_source_rollback_in_current_run():
    graph = FactGraph(run_scope="run")
    graph.begin(fixture_id(__name__, "a1"), 1, "entity")
    graph.begin(fixture_id(__name__, "b1"), 2, "annotation")
    with graph.author(fixture_id(__name__, "a1")):
        entity = EntityInput(name="Alice", entity_type="character", description="来源章专属")
        graph.register_entities([entity])
        graph.record_entity_ops([entity], chapter_id=1)
    identifier = graph.entity_id("Alice", "character")
    graph.reference_entities(
        fixture_id(__name__, "b1"), [{"entity_id": identifier, "name": "Alice", "entity_type": "character"}]
    )
    graph.confirm(fixture_id(__name__, "b1"))
    graph.rollback(fixture_id(__name__, "a1"))
    assert graph.display_name(graph.resolve_entity_id(identifier, label="actual reference")) == "Alice"
    # 回滚的源章不留下实体状态（只有保留侧的引用支持）
    assert graph.entity_attributes.get(entity_key("Alice", "character"), {}) == {}
    assert graph.drain_ops(fixture_id(__name__, "b1"))["entity_ops"] == []


def test_single_work_tree_recovery_preserves_other_inflight_nodes():
    trees = EventTrees("run")
    trees.begin(fixture_id(__name__, "o1"))
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
        event_id="other-node",
        from_chapter_id=1,
        to_chapter_id=1,
    )
    trees.sync(fixture_id(__name__, "o1"), 3, [other])
    saved = other.model_copy(update={"node_id": "saved-node", "tree_id": "saved-tree"})
    snapshot = {
        "author": fixture_id(__name__, "s1"),
        "nodes": {
            "saved-node": {
                "author": fixture_id(__name__, "s1"),
                "chapter_id": 1,
                "content": saved.model_dump(mode="json"),
            }
        },
        "connections": {},
        "actions": {},
    }
    trees.recover_work(snapshot)
    trees.recover_work(snapshot)
    assert trees.read("other-node")["saved"] is False
    assert trees.read("saved-node")["saved"] is True
    assert fixture_id(__name__, "o1") in trees.executions


def test_single_work_case_recovery_restores_own_exclusion_and_preserves_other_owner():
    pool = CasePool("run")
    saved, other = "s1", fixture_id(__name__, "o1")
    pool.begin(saved)
    pool.begin(other)
    own = pool.push("character", "Own case", saved)
    external = pool.push("character", "Other case", other)
    pool.promise(own["case_id"], saved)

    pool.promise(external["case_id"], other)
    snapshot = {
        "author": saved,
        "registrations": {own["case_id"]: own},
        "promises": pool.promises_for(saved),
    }
    pool.confirm(saved)
    pool.recover_work(snapshot)
    pool.recover_work(snapshot)
    assert pool.case_runtime[own["case_id"]]["owner"] == saved
    assert pool.case_runtime[own["case_id"]]["promised"] is True
    assert pool.case_runtime[external["case_id"]]["owner"] == other
    assert pool.case_runtime[external["case_id"]]["promised"] is True
    assert pool.promises_for(saved) == [own["case_id"]]
    pool.confirm(saved)
    # 确认只标记保存完成：承诺与归属不退回
    assert pool.case_runtime[own["case_id"]]["owner"] == saved


def test_full_case_restore_is_idempotent_and_forgets_discarded_contributions(db_session):
    """真实存储重载：重复恢复幂等，废弃作者的支持与交付不被恢复"""
    import json

    from src.case_pool.contributions import CaseContribution
    from src.storage.models import Agent
    from tests.support.chapter_annotation_helpers import create_run_with_chunks

    _novel, run_id = create_run_with_chunks(db_session, texts=["原文一。", "原文二。"], chapter_ids=[1, 2])
    # 作者身份是真实执行号；案例支持必须引用真实执行：
    # (run, chapter, role) 唯一，因此两个作者落在两章
    a, b = new_id(), new_id()
    for author, _chapter_id in ((a, 1), (b, 2)):
        db_session.add(
            Agent(id=author, run_id=run_id, type="annotation", status="success")
        )
    db_session.flush()
    pool = CasePool(run_id)
    pool.begin(a)
    pool.begin(b)
    first = pool.push("character", "Actual case", a)
    second = pool.push("character", "Second case", b)
    assert pool.promise(first["case_id"], a)["status"] == "promised"
    assert pool.promise(second["case_id"], b)["status"] == "promised"

    def contribution(author):
        snapshot = {
            "created_case_ids": sorted(pool.created.get(author, set())),
            "registrations": {key: pool.cases[key] for key in pool.registrations[author]},
            "promises": pool.promises_for(author),
        }
        return CaseContribution(run_id, author, json.dumps(snapshot, ensure_ascii=False))

    assert pool.save_work(storage_for(db_session), contribution(a)) == []
    assert pool.save_work(storage_for(db_session), contribution(b)) == []
    db_session.flush()

    restored = CasePool(run_id)
    restored.restore_storage(storage_for(db_session), set())
    restored.restore_storage(storage_for(db_session), set())
    # 承诺痕迹随交付重建：每作者 = 承诺行 + 写交付行
    assert restored.promises_for(a) == [first["case_id"]] and restored.promises_for(b) == [second["case_id"]]
    assert restored.case_runtime[first["case_id"]]["promised"] is True
    assert restored.case_runtime[second["case_id"]]["promised"] is True
    from src.storage.repositories.annotation_recovery import prune_cases
    prune_cases(db_session, run_id, {b})
    db_session.commit()
    restored.restore_storage(storage_for(db_session), {b})
    assert [item["case_id"] for item in restored.search()] == [first["case_id"]]
    restored.begin(fixture_id(__name__, "later"))
    restored.rollback(fixture_id(__name__, "later"))
    assert restored.search()[0]["submitted"] is True
