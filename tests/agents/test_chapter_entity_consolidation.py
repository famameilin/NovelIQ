"""章末程序与正式保存链的行为验收，使用隔离 PostgreSQL 和模型桩"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

from src.agents.annotation.entity_refs import ensure_entity_ref
from src.agents.messages import AssistantMessage
from src.config import settings
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import EntityInput
from src.fact_graph.read.alias import build_alias_resolution
from src.fact_graph.read.annotations import fetch_chapter_dialogues_full
from src.fact_graph.read.references import EntityReferenceProjection
from src.fact_graph.read.service import KnowledgeGraphAuthorityService
from src.storage.models import (
    ChapterAnnotation,
    CompleteEvent,
    EventParticipant,
    GraphEntity,
    GraphFact,
)
from src.storage.repositories.graph.repository import GraphRepository
from src.workflows.annotate import run_annotate
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.model_stream_adapter import StreamedFakeModelMixin
from tests.support.storage_fixtures import fixture_id, storage_for


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
        return AssistantMessage(
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


def test_rich_contributions_keep_work_updates_and_auto_registration_support() -> None:
    graph = FactGraph(run_scope="source-union")
    graph.begin(fixture_id(__name__, "s"), 1, "entity")
    graph.begin(fixture_id(__name__, "e"), 1, "event")
    with graph.author(fixture_id(__name__, "s")):
        for entity in [
            EntityInput(
                name="张三", entity_type="character", tags=["旧标签"], description="来历一", representative=True
            ),
            EntityInput(name="张三", entity_type="character", tags=["结构标签"], description="来历二"),
        ]:
            graph.register_entities([entity], present={"tags", "description", "representative"})
            graph.record_entity_ops([entity], chapter_id=1, present={"tags", "description", "representative"})
    with graph.author(fixture_id(__name__, "e")):
        ensure_entity_ref(graph, "张三", "character", chapter_id=1)
        entity = EntityInput(name="张三", entity_type="character", tags=["事件标签"])
        graph.register_entities([entity], present={"tags"})
        graph.record_entity_ops([entity], chapter_id=1, present={"tags"})
    key = graph.entity_key("张三", "character")
    assert set(graph.entity_tags[key]) == {"结构标签", "事件标签"}
    assert graph.entity_attributes[key] == {"description": "来历二", "is_representative": True}
    with graph.author(fixture_id(__name__, "e")):
        entity = EntityInput(name="张三", entity_type="character", tags=[], representative=False)
        graph.register_entities([entity], present={"tags", "representative"})
        graph.record_entity_ops([entity], chapter_id=1, present={"tags", "representative"})
    assert graph.entity_tags[key] == ["结构标签"]
    assert graph.entity_attributes[key] == {"description": "来历二"}
    assert len(graph.entity_names) == 1


def test_other_lane_rollback_does_not_remove_existing_reference_identity() -> None:
    graph = FactGraph(run_scope="concurrent-reference")
    graph.begin(fixture_id(__name__, "s"), 1, "entity")
    graph.begin(fixture_id(__name__, "e"), 1, "event")
    with graph.author(fixture_id(__name__, "s")):
        key = ensure_entity_ref(graph, "张三", "character", chapter_id=1)
    with graph.author(fixture_id(__name__, "e")):
        assert ensure_entity_ref(graph, "张三", "character", chapter_id=1) == key
    graph.rollback(fixture_id(__name__, "s"))
    assert graph.entity_id_for_key(key) is not None
    assert len(graph.entity_names) == 1


def test_runtime_and_reader_keep_conflicting_identity_component() -> None:
    graph = FactGraph(run_scope="formal-identity")
    graph.begin(fixture_id(__name__, "invocation"), 1, "annotation")
    with graph.author(fixture_id(__name__, "invocation")):
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
    graph.contributions[fixture_id(__name__, "invocation")]["relation_link_ops"] = operations
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
            "event": (
                '\ncreated = write_event(items=[dict(el="p", evidence=1, title="张三出门", problem="明确事件问题",\n'
                '      summary="张三出门", event_type="行动", status="ongoing",\n'
                '      characters=[{"name": "老张", "entity_type": "character", "role": "主体", '
                '"narrative_role": "主体", "action": "出门", "emotion": 0}])])'
                "\nfinish()\n"
            ),
            "metric": """
dialogue(candidate_index=1, verdict="dialogue", evidence=1, speaker={"name": "老张", "entity_type": "character"})
metric(summary="出门", emotional_valence=0, narrative_function="铺垫")
finish()
""",
        }
    )
    with patch("src.agents.model_client.build_chat_model", return_value=model):
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
        assert await run_annotate(run_id, storage_for(db_session), novel_id=novel_id) == (1, 0, 1)
    assert model.calls == 3
    db_session.expire_all()
    records = _annotation_records(db_session, run_id)
    assert len(records) == 3

    entities = {
        row.canonical_name: row for row in db_session.scalars(select(GraphEntity).where(GraphEntity.run_id == run_id))
    }
    assert set(entities) == {"张三", "老张"}
    projection = EntityReferenceProjection.load(storage_for(db_session), run_id)
    assert projection.resolution.resolve_entity_id(entities["老张"].entity_id) == entities["张三"].entity_id
    snapshots = {row.name: row for row in GraphRepository(db_session).fetch_latest_entity_rows(run_id)}
    assert set(snapshots["张三"].tags) == {"结构标签"}
    assert snapshots["张三"].attributes["is_representative"] is True
    assert snapshots["张三"].attributes["description"] == "张三的介绍"

    declaration = db_session.scalars(
        select(CompleteEvent).where(CompleteEvent.annotation_record_id.in_([record.record_id for record in records]))
    ).one()
    participants = list(
        db_session.scalars(select(EventParticipant).where(EventParticipant.event_id == declaration.event_id))
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
    assert fetch_chapter_dialogues_full(storage_for(db_session), run_id)[0].speaker == ["张三"]

    descriptions = {
        fact.description_value
        for fact in db_session.scalars(
            select(GraphFact).where(
                GraphFact.entity_id == entities["张三"].entity_id,
                GraphFact.description_value.is_not(None),
            )
        )
    }
    assert descriptions == {"张三的介绍"}

    authority = KnowledgeGraphAuthorityService(GraphRepository(db_session)).build_level1_snapshot(run_id)
    assert [row.name for row in authority.canonical_entities] == ["张三"]
    assert authority.confirmed_relations == []


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
