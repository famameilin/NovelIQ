"""章末程序与正式保存链的行为验收，使用隔离 PostgreSQL 和模型桩"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import delete, func, select

from src.agents.annotation.agent import AnnotationAgent
from src.agents.annotation.chapter_consolidation import (
    PROGRAM_CODE,
    RULE_VERSION,
    case_description,
    consolidate_chapter,
)
from src.agents.annotation.entity_refs import ensure_entity_ref
from src.case_pool import CasePool
from src.config import settings
from src.event_bus import EventBus, Message
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import EntityInput
from src.fact_graph.read.alias import build_alias_resolution
from src.fact_graph.read.annotations import fetch_chapter_dialogues_full
from src.fact_graph.read.references import EntityReferenceProjection
from src.fact_graph.read.service import KnowledgeGraphAuthorityService
from src.storage.db import get_session_factory
from src.storage.models import (
    BookCase,
    CaseEntry,
    ChapterAnnotation,
    DeclarationParticipant,
    EventDeclaration,
    Execution,
    GraphEntity,
    GraphFact,
    GraphRelation,
    WorkItem,
)
from src.storage.repositories.graph.repository import GraphRepository
from src.workflows.annotate import run_annotate
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.model_stream_adapter import StreamedFakeModelMixin


class _ProgramModel(StreamedFakeModelMixin):
    """程序面模型桩：每次调用交一段 CodeAct 程序"""

    model_name = "test_model"

    def __init__(self, code: str = "") -> None:
        self.code = code
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        return AIMessage(
            content="", tool_calls=[{"name": "execute_code", "args": {"code": self.code}, "id": f"call{self.calls}"}]
        )


class _RoleModel(_ProgramModel):
    """按注入消息里的角色标记交对应程序的长章模型桩"""

    def __init__(self, codes: dict[str, str]) -> None:
        super().__init__("")
        self.codes = codes

    async def ainvoke(self, messages):
        text = str(messages[1].content)
        for role, code in self.codes.items():
            if f'role="{role}"' in text:
                self.code = code
                break
        return await super().ainvoke(messages)


def _annotation_records(db_session, run_id):
    """run 的正式标注产物行（run_annotate 自提交，查询必须按 run 限定）"""
    return list(db_session.scalars(select(ChapterAnnotation).where(ChapterAnnotation.run_id == run_id)))


def _program_works(db_session, run_id):
    return list(
        db_session.scalars(
            select(WorkItem).where(WorkItem.program_run_id == run_id, WorkItem.program_code == PROGRAM_CODE)
        )
    )


def _receipt_facts(db_session, run_id):
    program_ids = [work.work_id for work in _program_works(db_session, run_id)]
    if not program_ids:
        return []
    return list(db_session.scalars(select(GraphFact).where(GraphFact.program_work_id.in_(program_ids))))


def _program_registered_supports(db_session, run_id):
    """章末核对登记的问题案例支持行（程序 work 形状）；空=核对无问题"""
    program_ids = select(WorkItem.work_id).where(WorkItem.program_run_id == run_id)
    return list(db_session.scalars(select(CaseEntry).where(CaseEntry.program_work_id.in_(program_ids))))


def _program_case_ids(db_session, run_id) -> list[str]:
    return [str(support.case_id) for support in _program_registered_supports(db_session, run_id)]


def _run_issue_cases(db_session, run_id):
    """章末核对登记的问题案例行（有正式目标的案例登记运行列为空，须经程序支持行归属）"""
    return [db_session.get(BookCase, case_id) for case_id in _program_case_ids(db_session, run_id)]


def _drop_program_receipt(db_session, run_id) -> None:
    """删除章末回执（事实+程序 work），让核对可以在测试里按新来源重跑"""
    work_ids = [work.work_id for work in _program_works(db_session, run_id)]
    if not work_ids:
        return
    db_session.execute(delete(GraphFact).where(GraphFact.program_work_id.in_(work_ids)))
    db_session.execute(delete(CaseEntry).where(CaseEntry.program_work_id.in_(work_ids)))
    db_session.execute(delete(WorkItem).where(WorkItem.work_id.in_(work_ids)))
    db_session.flush()


def test_rich_contributions_keep_work_updates_and_auto_registration_support() -> None:
    graph = FactGraph(run_scope="source-union")
    graph.begin("s", 1, "entity")
    graph.begin("e", 1, "event")
    with graph.author("s"):
        for entity in [
            EntityInput(
                name="张三", entity_type="character", tags=["旧标签"], description="来历一", representative=True
            ),
            EntityInput(name="张三", entity_type="character", tags=["结构标签"], description="来历二"),
        ]:
            graph.register_entities([entity], present={"tags", "description", "representative"})
            graph.record_entity_ops([entity], chapter_id=1, present={"tags", "description", "representative"})
    with graph.author("e"):
        ensure_entity_ref(graph, "张三", "character", chapter_id=1)
        entity = EntityInput(name="张三", entity_type="character", tags=["事件标签"])
        graph.register_entities([entity], present={"tags"})
        graph.record_entity_ops([entity], chapter_id=1, present={"tags"})
    key = graph.entity_key("张三", "character")
    assert set(graph.entity_tags[key]) == {"结构标签", "事件标签"}
    assert graph.entity_attributes[key] == {"description": "来历二", "is_representative": True}
    with graph.author("e"):
        entity = EntityInput(name="张三", entity_type="character", tags=[], representative=False)
        graph.register_entities([entity], present={"tags", "representative"})
        graph.record_entity_ops([entity], chapter_id=1, present={"tags", "representative"})
    assert graph.entity_tags[key] == ["结构标签"]
    assert graph.entity_attributes[key] == {"description": "来历二"}
    assert len(graph.entity_names) == 1


def test_other_lane_rollback_does_not_remove_existing_reference_identity() -> None:
    graph = FactGraph(run_scope="concurrent-reference")
    graph.begin("s", 1, "entity")
    graph.begin("e", 1, "event")
    with graph.author("s"):
        key = ensure_entity_ref(graph, "张三", "character", chapter_id=1)
    with graph.author("e"):
        assert ensure_entity_ref(graph, "张三", "character", chapter_id=1) == key
    graph.rollback("s")
    assert graph.entity_id_for_key(key) is not None
    assert len(graph.entity_names) == 1


def test_runtime_and_reader_keep_conflicting_identity_component() -> None:
    graph = FactGraph(run_scope="formal-identity")
    graph.begin("invocation", 1, "annotation")
    with graph.author("invocation"):
        keys = [ensure_entity_ref(graph, name, "character", chapter_id=1) for name in ["张三", "老张", "张哥"]]
    operations = [
        {"from_entity": keys[0], "to_entity": keys[1], "relation_type": "同一人物", "identity_kind": "same"},
        {"from_entity": keys[1], "to_entity": keys[2], "relation_type": "同一人物", "identity_kind": "same"},
        {
            "from_entity": keys[0],
            "to_entity": keys[2],
            "relation_type": "同一人物",
            "identity_kind": "different",
            "change_kind": "break",
        },
    ]
    graph.contributions["invocation"]["relation_link_ops"] = operations
    graph._fold()
    ids = [graph.entity_id_for_key(key) for key in keys]
    relations = [
        SimpleNamespace(
            from_entity_id=ids[0],
            to_entity_id=ids[1],
            is_active=True,
            relation_semantics="same_character",
            attributes={},
        ),
        SimpleNamespace(
            from_entity_id=ids[1],
            to_entity_id=ids[2],
            is_active=True,
            relation_semantics="same_character",
            attributes={},
        ),
        SimpleNamespace(
            from_entity_id=ids[0],
            to_entity_id=ids[2],
            is_active=False,
            relation_semantics="same_character",
            attributes={"identity_kind": "different"},
        ),
    ]
    entities = [
        SimpleNamespace(entity_id=identifier, name=graph.entity_names[key], attributes={})
        for identifier, key in zip(ids, keys, strict=True)
    ]
    reader = build_alias_resolution(relations, entities=entities)
    assert set(reader.conflicts) == set(ids)
    assert graph.identity_resolution().conflicts == reader.conflicts
    assert all(graph.resolve_key(key) == key for key in keys)
    assert graph.alias_group(keys[0]) == []
    # 正式撤回后不把旧不同身份断言复活为永久冲突
    operations.append(
        {"from_entity": keys[0], "to_entity": keys[2], "relation_type": "同一人物", "change_kind": "retract"}
    )
    graph._fold()
    assert graph.identity_resolution().conflicts == {}


@pytest.mark.asyncio
async def test_chapter_transaction_preserves_sources_and_four_reference_projection(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings.models.annotation, "sub_chunk_max_chars", 2)
    novel_id, run_id = create_run_with_chunks(db_session, texts=["“出门。”张三又称老张，找李四。"])

    model = _RoleModel(
        {
            "entity": """
entity(id="a", name="张三", entity_type="character", tags=["结构标签"],
       description="张三的介绍", representative=True, evidence=1)
relation(from_entity={"name": "张三", "entity_type": "character"},
         to_entity={"name": "老张", "entity_type": "character"}, relation_type="同一人物")
finish()
""",
            "event": """
entity(id="a", name="张三", entity_type="character", tags=["事件标签"], description="另一份介绍", evidence=1)
event(el="p", evidence=1, title="张三出门", problem="明确事件问题",
      summary="张三出门", event_type="行动", status="ongoing")
participants(el="p", items=[{"name": "老张", "entity_type": "character", "role": "主体"}])
relation(from_entity={"name": "老张", "entity_type": "character"},
         to_entity={"name": "李四", "entity_type": "character"}, relation_type="盟友")
finish()
""",
            "metric": """
dialogue(candidate_index=1, verdict="dialogue", evidence=1, speaker={"name": "老张", "entity_type": "character"})
metric(summary="出门", emotional_valence=0, narrative_function="铺垫")
finish()
""",
        }
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (1, 0, 1)
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (1, 0, 1)
    assert model.calls == 3
    db_session.expire_all()
    records = _annotation_records(db_session, run_id)
    assert len(records) == 3 and all(record.chapter_consolidation_version == RULE_VERSION for record in records)
    works = _program_works(db_session, run_id)
    assert len(works) == 1 and works[0].program_invocation_key.startswith("chapter:1:")
    facts = _receipt_facts(db_session, run_id)
    assert len(facts) == 1
    # 声明事件按裁定自动进池；核对零问题 = 没有任何程序登记的问题案例支持
    assert _program_registered_supports(db_session, run_id) == []

    entities = {
        row.canonical_name: row for row in db_session.scalars(select(GraphEntity).where(GraphEntity.run_id == run_id))
    }
    assert set(entities) == {"张三", "老张", "李四"}
    projection = EntityReferenceProjection.load(db_session, run_id)
    assert projection.resolution.resolve_entity_id(entities["老张"].entity_id) == entities["张三"].entity_id
    snapshots = {
        row.name: row
        for row in GraphRepository(db_session).fetch_latest_entity_rows(run_id)
    }
    assert set(snapshots["张三"].tags) == {"结构标签", "事件标签"}
    assert snapshots["张三"].attributes["is_representative"] is True
    assert snapshots["张三"].attributes["description"] == "另一份介绍"

    declaration = db_session.scalars(select(EventDeclaration).where(EventDeclaration.record_id.in_(
        [record.record_id for record in records]
    ))).one()
    participants = list(
        db_session.scalars(
            select(DeclarationParticipant).where(DeclarationParticipant.declaration_id == declaration.declaration_id)
        )
    )
    projected = projection.participants(
        [
            {
                "entity": {"entity_id": str(row.entity_id)},
                "role": row.role,
                "action": row.action,
                "emotion": row.emotion,
            }
            for row in participants
        ]
    )
    assert projected[0]["entity"]["name"] == "张三"
    assert fetch_chapter_dialogues_full(db_session, run_id)[0].speaker == ["张三"]

    descriptions = {
        fact.description_value
        for fact in db_session.scalars(
            select(GraphFact).where(
                GraphFact.entity_id == entities["张三"].entity_id,
                GraphFact.description_value.is_not(None),
            )
        )
    }
    assert descriptions == {"张三的介绍", "另一份介绍"}

    authority = KnowledgeGraphAuthorityService(GraphRepository(db_session)).build_level1_snapshot(run_id)
    assert [row.name for row in authority.canonical_entities] == ["张三", "李四"]
    assert [(row.from_name, row.to_name) for row in authority.confirmed_relations] in [
        [("张三", "李四")],
        [("李四", "张三")],
    ]


@pytest.mark.asyncio
async def test_pending_failure_rolls_back_and_resume_retries_only_program(db_session, monkeypatch) -> None:
    novel_id, run_id = create_run_with_chunks(db_session, texts=["张三出门。"])
    model = _ProgramModel(
        'entity(id="a", name="张三", entity_type="character", evidence=1)\n'
        'metric(summary="出门", emotional_valence=0, narrative_function="铺垫")\nfinish()'
    )
    original = CasePool.save_pending

    def fail_after_case(self, session, descriptions, *, author):
        original(self, session, descriptions, author=author)
        raise RuntimeError("模拟章末事务故障")

    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        with monkeypatch.context() as context:
            context.setattr(CasePool, "save_pending", fail_after_case)
            with pytest.raises(RuntimeError, match="模拟章末事务故障"):
                await run_annotate(run_id, db_session, novel_id=novel_id)
        db_session.expire_all()
        assert len(_annotation_records(db_session, run_id)) == 1
        assert _program_registered_supports(db_session, run_id) == []
        assert _program_works(db_session, run_id) == [] and _receipt_facts(db_session, run_id) == []
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (1, 0, 1)
        assert await run_annotate(run_id, db_session, novel_id=novel_id) == (1, 0, 1)
    assert model.calls == 1
    db_session.expire_all()
    issue_cases = _run_issue_cases(db_session, run_id)
    assert len(issue_cases) == 1
    case = issue_cases[0]
    assert case.review_state is None and "码=实体无引用" in case.description and "段=" in case.description
    supports = list(db_session.scalars(select(CaseEntry).where(CaseEntry.case_id == case.case_id)))
    assert len(supports) == 1 and supports[0].program_work_id is not None
    assert db_session.scalar(select(GraphEntity).where(GraphEntity.run_id == run_id)) is not None
    case.review_state = "deferred"
    db_session.commit()
    # 原有办理状态即使没有新增交付，程序登记也不得重置
    program_work = _program_works(db_session, run_id)[0]
    pool = CasePool(run_id)
    pool.save_pending(
        db_session,
        [
            (
                "character",
                case.description,
                {"node_id": "a", "name": "张三", "entity_type": "character", "reason": "unreferenced_entity"},
            )
        ],
        author=program_work.work_id,
    )
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(BookCase, case.case_id).review_state == "deferred"


@pytest.mark.asyncio
async def test_historical_completed_chapter_has_no_backfill(db_session) -> None:
    novel_id, run_id = create_run_with_chunks(db_session, texts=["张三出门。"])
    model = _ProgramModel('metric(summary="出门", emotional_valence=0, narrative_function="铺垫")\nfinish()')
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        await run_annotate(run_id, db_session, novel_id=novel_id)
        record = _annotation_records(db_session, run_id)[0]
        record.chapter_consolidation_version = "chapter-entity-consolidation-2000-01-01"
        _drop_program_receipt(db_session, run_id)
        db_session.commit()
        await run_annotate(run_id, db_session, novel_id=novel_id)
    assert model.calls == 1
    assert _program_works(db_session, run_id) == [] and _receipt_facts(db_session, run_id) == []


def test_case_template_retains_location_reason_evidence_and_marks_long_name() -> None:
    description = case_description(
        {
            "node_id": "00000000-0000-0000-0000-000000000001",
            "name": "长名字" * 100,
            "entity_type": "character",
            "reason": "unreferenced_entity",
            "evidence": [{"paragraph_id": 695}, {"paragraph_id": 701}],
        }
    )
    assert len(description) <= 100
    assert "…；类=character；码=实体无引用；段=695" in description


def test_required_lane_must_be_saved_before_consolidation(db_session) -> None:
    _, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    with pytest.raises(ValueError, match="必需角色"):
        consolidate_chapter(db_session, run_id, 1, CasePool(run_id))


def test_ambiguous_representatives_and_participant_variants_are_preserved() -> None:
    entities = [
        SimpleNamespace(
            entity_id=identifier, name=name, entity_type="character", attributes={"is_representative": True}
        )
        for identifier, name in [("a", "张三"), ("b", "老张")]
    ]
    relation = SimpleNamespace(
        from_entity_id="a", to_entity_id="b", relation_semantics="same_character", is_active=True, attributes={}
    )
    resolution = build_alias_resolution([relation], entities=entities)
    assert resolution.conflicts == {"a": "representative_ambiguous", "b": "representative_ambiguous"}
    assert resolution.representative_by_alias == {}
    entities[1].attributes = {}
    projection = EntityReferenceProjection(
        {row.entity_id: row for row in entities}, build_alias_resolution([relation], entities=entities)
    )
    participant = {
        "entity": {"entity_id": "b", "name": "老张", "entity_type": "character"},
        "role": "主体",
        "action": "出门",
        "emotion": 1,
    }
    variants = projection.participants(
        [participant, participant, {**participant, "action": "进门"}, {**participant, "role": "目标"}]
    )
    assert len(variants) == 3
    assert {item["entity"]["entity_id"] for item in variants} == {"a"}
    assert participant["entity"]["entity_id"] == "b"


@pytest.mark.asyncio
async def test_preceding_saved_reference_prevents_false_orphan(db_session, monkeypatch) -> None:
    """前序已保存引用挡住误报：固定反序完成（第 2 章先跑完），收尾重算必须清掉早跑误报"""
    import asyncio

    novel_id, run_id = create_run_with_chunks(
        db_session, texts=["张三首次出门。", "张三再次出门。"], chapter_ids=[1, 2]
    )
    model = _ProgramModel()
    model.codes = {
        "首次": (
            "event(el='p', evidence=1, title='张三首次出门', prob"
            "lem='明确事件问题', summary='张三首次出门', event_type='"
            "行动', status='ongoing')\nparticipants(el='p', ite"
            "ms=[{'name': '张三', 'entity_type': 'character', "
            "'role': '主体'}])\nmetric(summary='首次', emotiona"
            "l_valence=0, narrative_function='铺垫')\nfinish()"
        ),
        "再次": (
            'entity(id="a", name="张三", entity_type="character", description="新陈述", evidence=1)\n'
            'metric(summary="再次", emotional_valence=0, narrative_function="铺垫")\nfinish()'
        ),
    }

    async def ainvoke(messages):
        text = str(messages[1].content)
        key = "首次" if "首次" in text else "再次"
        if key == "首次":
            # 固定乱序：第 1 章晚交程序，第 2 章整条链路先保存并先触发核对
            await asyncio.sleep(1.0)
        model.code = model.codes[key]
        return await _ProgramModel.ainvoke(model, messages)

    model.ainvoke = ainvoke  # type: ignore[method-assign]
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        await run_annotate(run_id, db_session, novel_id=novel_id)
    db_session.expire_all()
    assert len(_program_works(db_session, run_id)) == 2
    assert _program_registered_supports(db_session, run_id) == []


@pytest.mark.asyncio
async def test_last_saved_agent_triggers_before_whole_book_pool_returns(
    db_session, configured_model_pool, monkeypatch
) -> None:
    import asyncio

    from src.agents.annotation import chapter_consolidation

    novel_id, run_id = create_run_with_chunks(db_session, texts=["早章。", "后章。"], chapter_ids=[1, 2])
    later_consolidated = asyncio.Event()
    loop = asyncio.get_running_loop()
    original = chapter_consolidation.consolidate_chapter

    def observed(session, run_id, chapter_id, cases, **kwargs):
        result = original(session, run_id, chapter_id, cases, **kwargs)
        if chapter_id == 2 and result["status"] == "saved":
            loop.call_soon_threadsafe(later_consolidated.set)
        return result

    class OrderedModel(_ProgramModel):
        async def ainvoke(self, messages):
            if "早章" in str(messages[1].content):
                await asyncio.wait_for(later_consolidated.wait(), 5)
            return await super().ainvoke(messages)

    monkeypatch.setattr(chapter_consolidation, "consolidate_chapter", observed)
    model = OrderedModel('metric(summary="原文", emotional_valence=0, narrative_function="铺垫")\nfinish()')
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        await run_annotate(run_id, db_session, novel_id=novel_id)
    assert later_consolidated.is_set() and model.calls == 2


@pytest.mark.asyncio
async def test_unregistered_participant_stays_and_enters_pending(db_session) -> None:
    novel_id, run_id = create_run_with_chunks(db_session, texts=["张三出门。"])
    model = _ProgramModel(
        "event(el='p', evidence=1, title='张三出门', probl"
        "em='明确事件问题', summary='张三出门', event_type='行动',"
        " status='ongoing')\nmetric(summary='出门', emoti"
        "onal_valence=0, narrative_function='铺垫')\nfini"
        "sh()"
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        await run_annotate(run_id, db_session, novel_id=novel_id)
    db_session.expire_all()
    declaration = db_session.scalars(
        select(EventDeclaration).where(
            EventDeclaration.record_id.in_([record.record_id for record in _annotation_records(db_session, run_id)])
        )
    ).one()
    # 隔离测试直接构造未登记身份的参与者来源，验证核对登记案例且原样保留
    db_session.add(
        GraphEntity(
            entity_id="00000000-0000-0000-0000-0000000000cc",
            run_id=run_id,
            canonical_name="失联人物",
            entity_type="character",
        )
    )
    db_session.flush()
    db_session.add(
        DeclarationParticipant(
            participant_id="00000000-0000-0000-0000-0000000000dd",
            declaration_id=declaration.declaration_id,
            participant_ordinal=0,
            entity_id="00000000-0000-0000-0000-0000000000cc",
            role="主体",
        )
    )
    _drop_program_receipt(db_session, run_id)
    db_session.commit()
    result = consolidate_chapter(db_session, run_id, 1, CasePool(run_id))
    db_session.commit()
    assert result["status"] == "saved" and result["issues"] == 1
    descriptions = [case.description for case in _run_issue_cases(db_session, run_id)]
    assert any("码=参与者未登记" in description for description in descriptions)
    assert not any("码=过程无根" in description for description in descriptions)
    kept = db_session.get(DeclarationParticipant, "00000000-0000-0000-0000-0000000000dd")
    assert kept is not None and kept.entity_id == "00000000-0000-0000-0000-0000000000cc"


@pytest.mark.asyncio
async def test_dangling_relation_enters_pending_and_edge_survives(db_session) -> None:
    novel_id, run_id = create_run_with_chunks(db_session, texts=["张三出门。"])
    model = _ProgramModel(
        'entity(id="a", name="张三", entity_type="character", evidence=1)\n'
        'metric(summary="出门", emotional_valence=0, narrative_function="铺垫")\nfinish()'
    )
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        await run_annotate(run_id, db_session, novel_id=novel_id)
    db_session.expire_all()
    zhang = db_session.scalars(select(GraphEntity).where(GraphEntity.run_id == run_id)).one()
    execution = db_session.scalars(select(Execution).where(Execution.run_id == run_id)).one()
    # 隔离测试直接构造端点为未登记身份的正式关系事实，验证核对登记案例且关系边原样保留
    db_session.add(
        GraphEntity(
            entity_id="00000000-0000-0000-0000-0000000000ee",
            run_id=run_id,
            canonical_name="失联人物",
            entity_type="character",
        )
    )
    db_session.add(
        GraphRelation(
            relation_id="00000000-0000-0000-0000-0000000000ff",
            from_entity_id=zhang.entity_id,
            to_entity_id="00000000-0000-0000-0000-0000000000ee",
            relation_type="盟友",
        )
    )
    highest = db_session.scalar(
        select(func.max(GraphFact.operation_order)).where(
            GraphFact.direct_producer_execution_id == execution.execution_id
        )
    )
    db_session.add(
        GraphFact(
            direct_producer_execution_id=execution.execution_id,
            relation_id="00000000-0000-0000-0000-0000000000ff",
            relation_change_kind="assert",
            operation_order=(highest if highest is not None else -1) + 1,
        )
    )
    _drop_program_receipt(db_session, run_id)
    db_session.commit()
    result = consolidate_chapter(db_session, run_id, 1, CasePool(run_id))
    db_session.commit()
    assert result["status"] == "saved" and result["issues"] == 1
    descriptions = [case.description for case in _run_issue_cases(db_session, run_id)]
    assert any("码=关系悬空" in description for description in descriptions)
    survived = db_session.get(GraphRelation, "00000000-0000-0000-0000-0000000000ff")
    assert survived is not None and survived.to_entity_id == "00000000-0000-0000-0000-0000000000ee"


@pytest.mark.asyncio
async def test_checkpoint_save_failure_rolls_back_cases_and_retries_without_model(db_session) -> None:
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    novel_id, run_id = create_run_with_chunks(db_session, texts=["张三出门。"])
    model = _ProgramModel(
        'entity(id="a", name="张三", entity_type="character", evidence=1)\n'
        'metric(summary="出门", emotional_valence=0, narrative_function="铺垫")\nfinish()'
    )

    def reject_checkpoint(session, flush_context, instances):
        if any(isinstance(row, GraphFact) and row.program_work_id is not None for row in session.new):
            raise RuntimeError("模拟凭据写入故障")

    event.listen(Session, "before_flush", reject_checkpoint)
    try:
        with patch("src.model_pool.llm.build_chat_model", return_value=model):
            with pytest.raises(RuntimeError, match="模拟凭据写入故障"):
                await run_annotate(run_id, db_session, novel_id=novel_id)
    finally:
        event.remove(Session, "before_flush", reject_checkpoint)
    db_session.expire_all()
    assert _program_registered_supports(db_session, run_id) == []
    assert _program_works(db_session, run_id) == []
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        await run_annotate(run_id, db_session, novel_id=novel_id)
    assert model.calls == 1
    assert len(_program_works(db_session, run_id)) == 1


@pytest.mark.asyncio
async def test_ambiguous_formal_identity_enters_cases_without_deleting_nodes(db_session) -> None:
    novel_id, run_id = create_run_with_chunks(db_session, texts=["张三又叫老张。"])
    model = _ProgramModel("""
entity(id="a", name="张三", entity_type="character", representative=True, evidence=1)
entity(id="b", name="老张", entity_type="character", representative=True, evidence=1)
relation(from_entity={"name": "张三", "entity_type": "character"},
         to_entity={"name": "老张", "entity_type": "character"}, relation_type="同一人物")
metric(summary="称谓", emotional_valence=0, narrative_function="铺垫")
finish()
""")
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        await run_annotate(run_id, db_session, novel_id=novel_id)
    db_session.expire_all()
    descriptions = [case.description for case in _run_issue_cases(db_session, run_id)]
    assert len(descriptions) == 2 and all("码=代表判不定" in description for description in descriptions)
    assert len(list(db_session.scalars(select(GraphEntity).where(GraphEntity.run_id == run_id)))) == 2
    projection = EntityReferenceProjection.load(db_session, run_id)
    assert projection.resolution.representative_by_alias == {}


@pytest.mark.asyncio
async def test_agent_restores_case_memory_when_chapter_transaction_fails(db_session, monkeypatch) -> None:
    _, run_id = create_run_with_chunks(db_session, texts=["原文。"])
    agent = AnnotationAgent(EventBus(), run_id, get_session_factory(), novel_id="test")

    def fail(session, run_id, chapter_id, cases, **kwargs):
        cases.begin("program")
        cases.push("event", "模拟登记", "program")
        raise RuntimeError("故障")

    monkeypatch.setattr("src.agents.annotation.chapter_consolidation.consolidate_chapter", fail)
    try:
        with pytest.raises(RuntimeError, match="故障"):
            await agent.consolidate_chapter(
                Message(
                    topic="agent.consolidate_chapter",
                    source="test",
                    target=agent.address,
                    run_id=run_id,
                    payload={"chapter_id": 1},
                )
            )
        assert agent.case_pool.cases == {} and agent.case_pool.executions == set()
    finally:
        agent.close()
