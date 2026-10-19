"""全新 PostgreSQL schema 验收，不读取或改写现有业务结果"""

import json
from dataclasses import replace
from datetime import datetime
from secrets import token_hex
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from dotenv import dotenv_values, load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from src.storage import Storage
from src.storage.constraints import install_domain_constraints
from src.storage.database_url import resolve_database_url_from_env
from src.storage.errors import StorageError
from src.storage.models import Base
from src.storage.operations import OperationRunner
from src.storage.records.annotation_save import AnnotationSave
from src.storage.records.cases import CaseSave
from src.storage.records.diagnosis_save import DiagnosisReportSave
from src.storage.records.events import EventSave
from src.storage.records.evidence import EvidenceParagraph
from src.storage.records.facts import FactSave
from tests.support.storage_fixtures import task_for_run


@pytest.fixture(scope="module")
def isolated_storage():
    """只在独立测试数据库创建随机命名空间，清理范围仅为本夹具创建的 schema"""
    load_dotenv(".env")
    live_database_url = dotenv_values(".env").get("DATABASE_URL")
    assert isinstance(live_database_url, str), "必须明确开发库位置，才能核验测试数据库隔离"
    live_url = make_url(live_database_url)
    test_url = make_url(resolve_database_url_from_env("TEST_DATABASE"))
    assert (live_url.host, live_url.port, live_url.database) != (test_url.host, test_url.port, test_url.database)
    schema = "storage_contract_" + token_hex(8)
    engine = create_engine(
        test_url,
        connect_args={"options": f"-c search_path={schema},public -c statement_timeout=10000"},
        execution_options={"schema_translate_map": {None: schema}},
    )
    created = False
    try:
        with engine.begin() as connection:
            extensions = set(connection.scalars(text("SELECT extname FROM pg_extension")))
            assert {"vector", "pg_trgm"} <= extensions
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            created = True
        Base.metadata.create_all(engine)
        install_domain_constraints(engine)
        factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
        yield Storage(_runner=OperationRunner(factory)), engine, factory, schema
    finally:
        if created:
            with engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        engine.dispose()


@pytest.fixture
def stored_run(isolated_storage):
    storage, _, _, _ = isolated_storage
    novel_id = storage.new_id()
    storage.novels.create(
        novel_id=novel_id,
        filename="contract.txt",
        title="测试小说",
        file_path="contract.txt",
        file_size=12,
        upload_time=datetime.now(),
    )
    run_id = storage.runs.create_run(novel_id)
    return storage, run_id


def test_35_tables_have_independent_uuid_primary_keys(isolated_storage):
    _, engine, _, schema = isolated_storage
    inspector = inspect(engine)
    tables = inspector.get_table_names(schema=schema)
    assert set(tables) == set(Base.metadata.tables)
    assert len(tables) == 32
    for table in tables:
        primary = inspector.get_pk_constraint(table, schema=schema)["constrained_columns"]
        assert len(primary) == 1, table
        columns = {row["name"]: row for row in inspector.get_columns(table, schema=schema)}
        assert str(columns[primary[0]]["type"]) == "UUID", table


def test_task_short_id_is_independent_and_run_uuid7(stored_run):
    storage, run_id = stored_run
    assert UUID(run_id).version == 7
    run = storage.runs.get_run(run_id)
    assert len(run["task_id"]) == 8
    assert run["task_id"] != task_for_run(run_id)
    assert storage.runs.get_run_by_task_id(run["task_id"])["run_id"] == run_id
    assert storage.runs.get_run_by_task_id("%") is None


def test_api_run_owner_check_uses_read_only_storage_and_exact_task_mapping(stored_run):
    from src.api.dependencies import require_run_for_novel
    from src.api.exceptions import NovelNotFoundError

    storage, run_id = stored_run
    run = storage.runs.get_run(run_id)
    assert require_run_for_novel(storage, run["novel_id"], run_id)["task_id"] == run["task_id"]
    with pytest.raises(NovelNotFoundError, match=run["task_id"]):
        require_run_for_novel(storage, storage.new_id(), run_id)


def test_chapter_has_generated_key_and_natural_unique_foreign_key(stored_run, isolated_storage):
    storage, run_id = stored_run
    chapter = SimpleNamespace(
        chapter_id=1,
        sequence=1,
        title="第一章",
        display_title="第一章",
        display_index_label=None,
        level=SimpleNamespace(value="chapter"),
        start_char=0,
        end_char=3,
    )
    storage.chapters.insert_chapters(run_id, [chapter])
    _, engine, _, schema = isolated_storage
    with engine.connect() as connection:
        row = connection.execute(
            text(f"SELECT id,run_id,chapter_id FROM {schema}.chapters WHERE run_id=:run"), {"run": run_id}
        ).one()
        assert UUID(str(row.id)).version == 7
        assert row.chapter_id == 1


def test_uuid4_identity_is_rejected_before_write(stored_run):
    storage, _ = stored_run
    with pytest.raises(StorageError, match="UUIDv7"):
        storage.novels.get(str(uuid4()))


def test_read_operation_cannot_write_and_returns_detached_values(isolated_storage):
    _, engine, factory, schema = isolated_storage
    runner = OperationRunner(factory)
    with pytest.raises(StorageError):
        runner.run(
            lambda session: session.execute(text(f"INSERT INTO {schema}.novels (novel_id) VALUES (gen_random_uuid())")),
            read_only=True,
        )
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT current_schema()")) == schema


@pytest.fixture
def prepared_chapter(stored_run):
    storage, run_id = stored_run
    text_value = "张三进门。"
    chapter = SimpleNamespace(
        chapter_id=1,
        sequence=1,
        title="第一章",
        display_title="第一章",
        display_index_label=None,
        level=SimpleNamespace(value="chapter"),
        start_char=0,
        end_char=len(text_value),
    )
    storage.chapters.insert_chapters(run_id, [chapter])
    storage.chapters.insert_chapter_texts(
        run_id, [SimpleNamespace(chapter_id=1, text=text_value, start=0, end=len(text_value))]
    )
    span = SimpleNamespace(
        paragraph_id=1,
        chapter_id=1,
        paragraph_index=0,
        source_paragraph_index=0,
        fragment_index=0,
        local_start_char=0,
        local_end_char=len(text_value),
        global_start_char=0,
        global_end_char=len(text_value),
        char_count=len(text_value),
        token_count=3,
        text=text_value,
    )
    storage.paragraphs.insert_paragraphs(run_id, [span])
    return storage, run_id, text_value


@pytest.fixture
def prepared_annotation(prepared_chapter):
    storage, run_id, text_value = prepared_chapter
    author, record_id, entity_id, event_id = [storage.new_id() for _ in range(4)]
    storage.audit.start_invocation(agent_id=author, run_id=run_id, role="annotation", chapter_id=1)
    entities = {entity_id: {"entity_id": entity_id, "name": "张三", "entity_type": "character"}}
    facts = {
        "entities": entities,
        "entity_ops": [
            {
                "entity_id": entity_id,
                "name": "张三",
                "entity_type": "character",
                "submitted_fields": ["tags"],
                "tags": ["主角"],
            }
        ],
        "relation_assert_ops": [],
        "plotline_ops": [],
    }
    content = {
        "node_id": event_id,
        "title": "进门",
        "problem": "谁进入房间",
        "summary": "张三进入房间",
        "event_type": "plot",
        "status": "ongoing",
        "progress": 0,
        "is_foreshadow_setup": False,
        "payoff_likelihood": None,
        "evidence_paragraph_id": 1,
        "participants": [{"entity": entity_id, "role": "参与者"}],
    }
    events = {"nodes": {event_id: {"author": author, "content": content}}, "actions": {}, "relations": {}}
    paragraphs = (EvidenceParagraph(1, 1, text_value, 0, len(text_value)),)
    case = CaseSave(run_id, author, json.dumps({"created_case_ids": [], "registrations": {}, "deliveries": []}))
    record = {
        "record_id": record_id,
        "agent_id": author,
        "run_id": run_id,
        "chapter_id": 1,
        "role": "annotation",
    }
    dialogue = {
        "dialogue_id": storage.new_id(),
        "run_id": run_id,
        "chapter_id": 1,
        "creation_agent_id": author,
        "candidate_key": "dialogue:1",
        "start_char": 0,
        "end_char": 2,
        "speaker_entity_id": entity_id,
        "tone": "平静",
        "is_inner_monologue": False,
    }
    label = {"assessment_id": storage.new_id(), "record_id": record_id, "paragraph_id": 1, "emotion": 1}
    request = AnnotationSave(
        record,
        FactSave(run_id, author, 1, paragraphs, json.dumps(facts), "[]"),
        EventSave(run_id, author, 1, paragraphs, json.dumps(events), json.dumps(entities)),
        case,
        (dialogue,),
        (label,),
    )
    return storage, run_id, request


def _counts_for_run(engine, schema, run_id):
    with engine.connect() as connection:
        return {
            name: connection.scalar(text(f"SELECT count(*) FROM {schema}.{name}"))
            for name in (
                "agent_annotations",
                "graph_entities",
                "graph_facts",
                "graph_fact_entity_tags",
                "event_declarations",
                "event_participants",
                "paragraph_evidence",
                "graph_dialogues",
                "agent_assessments",
            )
        }


def test_complete_annotation_and_replay_preserve_identifiers(prepared_annotation, isolated_storage):
    storage, run_id, request = prepared_annotation
    _, engine, _, schema = isolated_storage
    before = _counts_for_run(engine, schema, run_id)
    result = storage.annotations.save(request)
    assert result["annotation_id"] == request.record["record_id"]
    after = _counts_for_run(engine, schema, run_id)
    assert all(after[name] > before[name] for name in before)
    assert storage.annotations.save(request) == result
    assert _counts_for_run(engine, schema, run_id) == after
    from src.fact_graph.graph import FactGraph, entity_key

    graph = FactGraph(run_scope=run_id)
    graph.load_registry(storage)
    entity_id = next(iter(request.facts.snapshot()["entities"]))
    assert graph.entity_id_for_key(entity_key("张三", "character")) == entity_id
    restored = graph.load_saved_work(storage, request.record["agent_id"], request.record["record_id"])
    assert restored["entity_references"][0]["entity_id"] == entity_id
    assert storage.narrative.declaration_record_source(request.record["record_id"]).run_id == run_id


def test_last_annotation_component_failure_rolls_back_every_component(prepared_annotation, isolated_storage):
    storage, run_id, request = prepared_annotation
    _, engine, _, schema = isolated_storage
    before = _counts_for_run(engine, schema, run_id)
    # 最后的评估条目违反正式形状，前面已 flush 的声明、事实、对话也必须撤销
    bad = replace(
        request,
        labels=({"assessment_id": storage.new_id(), "record_id": request.record["record_id"], "paragraph_id": 1},),
    )
    with pytest.raises(StorageError):
        storage.annotations.save(bad)
    assert _counts_for_run(engine, schema, run_id) == before
    assert storage.annotations.inspect_saved(request.record["agent_id"])["record_id"] is None


def test_topic_facts_commit_together_and_failed_distribution_rolls_back(prepared_annotation, isolated_storage):
    storage, run_id, _ = prepared_annotation
    _, engine, _, schema = isolated_storage
    model = {
        "model_key": "paragraph_lda",
        "library_version": "test",
        "num_topics": 2,
        "parameters": {},
        "dictionary_size": 2,
        "training_document_count": 1,
        "inference_paragraph_count": 1,
        "artifact_key": "test",
    }
    from tests.support.storage_fixtures import save_topic_artifact
    save_topic_artifact(run_id, 2)
    with pytest.raises(ValueError, match="实际模型"):
        storage.paragraphs.save_topics(
            run_id, model=model, inferences=[(1, 3, 3, "complete", None, 1.0)], topics=[(1, 0, 0.4)]
        )
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text(f"SELECT lda_completed FROM {schema}.runs WHERE id=:run"), {"run": run_id}
            )
            is False
        )
    assert (
        storage.paragraphs.save_topics(
            run_id, model=model, inferences=[(1, 3, 3, "complete", None, 1.0)], topics=[(1, 0, 0.4), (1, 1, 0.6)]
        )
        == 2
    )


def test_diagnosis_failure_after_report_write_rolls_back(stored_run, isolated_storage):
    storage, run_id = stored_run
    session_id = storage.new_id()
    storage.audit.start_invocation(run_id=run_id, agent_id=session_id, role="report")
    report_id = storage.new_id()
    # 报告与评估已写入后，对话目标缺失造成失败，不能留下半份正式报告
    organization = {
        key: []
        for key in (
            "events",
            "containments",
            "relations",
            "reviewed_events",
            "declaration_reviews",
            "declaration_comparisons",
            "structure_reviews",
            "arcs",
            "outcomes",
            "event_arc_links",
            "event_outcome_links",
        )
    }
    organization["source_agent_id"] = session_id
    request = DiagnosisReportSave(
        run_id,
        session_id,
        {"report_id": report_id, "agent_id": session_id},
        (),
        json.dumps(organization),
        frozenset(),
        (),
        ({"candidate_key": "missing"},),
        (),
    )
    with pytest.raises(ValueError, match="对话候选"):
        storage.diagnosis.save_report(request)
    _, engine, _, schema = isolated_storage
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text(f"SELECT count(*) FROM {schema}.diagnosis_reports WHERE report_id=:id"), {"id": report_id}
            )
            == 0
        )
    assert storage.diagnosis.save_report(replace(request, dialogue_updates=()))["report_id"] == report_id




def test_domain_reads_restore_saved_graph_and_declarations(prepared_annotation):
    storage, run_id, request = prepared_annotation
    storage.annotations.save(request)
    from src.event_trees.read.foreshadowing import fetch_foreshadowing_sources
    from src.event_trees.trees import EventTrees
    from src.fact_graph.read.storage_projection import graph_projection

    graph = graph_projection(storage.graph).fetch_snapshot(run_id)
    assert len(graph.entities) == 1
    trees = EventTrees(run_id=run_id)
    restored = trees.load_saved_work(storage, request.record["agent_id"], request.record["record_id"])
    assert restored
    assert fetch_foreshadowing_sources(storage, run_id) == []


def test_audit_uuid_identifiers_and_sse_replay(prepared_annotation):
    storage, run_id, request = prepared_annotation
    agent_id = request.record["agent_id"]
    call_id = storage.audit.start_turn(
        run_id=run_id,
        task_type="annotation",
        call_type="agent",
        model="test",
        agent_id=agent_id,
        attempt_number=1,
        chapter_id=1,
        role="annotation",
        turn_index=1,
        context_summary={},
        request_messages=[],
        message_key=storage.new_id(),
    )
    assert UUID(call_id).version == 7
    storage.audit.record_tool_call(
        turn_id=call_id, call_index=0, tool_name="read", request_args={}, response={"ok": True}
    )
    storage.audit.finish_turn(
        call_id, raw_response={"ok": True},  error=None, timing={}, timing_notes=[], token_usage=None
    )
    from src.audit.queries import fetch_agent_turns, fetch_run_tool_calls, fetch_token_usage_stats

    turns = fetch_agent_turns(storage, run_id)
    assert turns[0].call_id == call_id
    tools = fetch_run_tool_calls(storage, run_id)
    assert UUID(tools[0].tool_call_id).version == 7
    assert fetch_token_usage_stats(storage, run_id)
    task_id = storage.runs.get_run(run_id)["task_id"]
    payload = {"message_id": storage.new_id(), "chapter_id": 1}
    emitted = storage.sse.emit(task_id, "test", payload)
    assert storage.sse.emit(task_id, "test", payload) == emitted
    from src.sse.persistence import SseMessageRepository

    repository = SseMessageRepository(lambda: storage)
    assert repository.replay(task_id, after_seq=0)




def test_result_and_diagnosis_queries_consume_storage_interfaces(prepared_annotation):
    storage, run_id, request = prepared_annotation
    storage.annotations.save(request)
    from src.api.services.results_queries.chapters import _fetch_chapter_annotations
    from src.api.services.results_queries.graph import _fetch_graph_snapshot
    from src.diagnosis.queries import DiagnosisQueries
    from src.linguistic.queries import aggregate_linguistic_features

    assert _fetch_graph_snapshot(run_id, storage)
    assert _fetch_chapter_annotations(run_id, storage)
    queries = DiagnosisQueries(storage)
    assert queries.fetch_pivot_blocks(run_id) == []
    assert queries.fetch_foreshadowing_sources(run_id) == []
    assert aggregate_linguistic_features(run_id, storage)


def test_default_workflow_factories_return_storage_without_connecting():
    from src.workflows.analysis.environment_initializer import EnvironmentInitializer
    from src.workflows.service import AnalysisService

    service = AnalysisService(SimpleNamespace(), SimpleNamespace())
    assert isinstance(service.session_factory(), Storage)
    assert isinstance(EnvironmentInitializer().session_factory(), Storage)




@pytest.mark.asyncio
async def test_formal_annotation_pipeline_commits_and_restores_without_model_replay(
    prepared_chapter, isolated_storage, monkeypatch
):
    from langchain_core.messages import AIMessage

    from src.config import settings
    from src.config.schemas.model import WeightedModelSettings
    from src.model_pool.capacity import MODEL_CAPACITY
    from src.storage import db
    from src.work.queries import chapter_annotations, is_annotate_complete
    from src.workflows.annotate import run_annotate
    from tests.support.model_stream_adapter import StreamedFakeModelMixin

    storage, run_id, _ = prepared_chapter
    _, _, factory, _ = isolated_storage
    novel_id = storage.runs.get_run(run_id)["novel_id"]

    class ProgramModel(StreamedFakeModelMixin):
        model_name = "storage-pipeline-test"
        calls = 0

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            assert self.calls == 1, "恢复不得重复调用模型"
            code = (
                "entity(id='a1', name='张三', entity_type='character', evidence=1)\n"
                "event(el='t1', evidence=1, title='张三进门', problem='能否进入',"
                " summary='张三进门', event_type='行动', status='ongoing')\n"
                "metric(summary='进门', emotional_valence=0, narrative_function='铺垫')\nfinish()"
            )
            return AIMessage(
                content="", tool_calls=[{"name": "execute_code", "args": {"code": code}, "id": "program-call"}]
            )

    model = ProgramModel()
    monkeypatch.setattr(db, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        settings.models,
        "model_pool",
        [WeightedModelSettings("storage-pipeline-test", "https://test.example/v1", "test-key", max_in_flight=1)],
    )
    monkeypatch.setattr("src.model_pool.llm.build_chat_model", lambda *args, **kwargs: model)
    MODEL_CAPACITY.reset()
    try:
        assert await run_annotate(run_id, storage, novel_id=novel_id) == (1, 0, 1)
        assert is_annotate_complete(storage, run_id)
        saved = chapter_annotations(storage, run_id)
        assert len(saved) == 1
        assert UUID(saved[0].output_id).version == 7
        assert await run_annotate(run_id, storage, novel_id=novel_id) == (1, 0, 1)
        assert model.calls == 1
    finally:
        MODEL_CAPACITY.reset()




def test_schema_guard_rejects_existing_composite_key_without_changing_it(isolated_storage):
    from src.storage.db import validate_existing_schema

    _, engine, _, _ = isolated_storage
    schema = "storage_old_" + token_hex(8)
    created = False
    try:
        with engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            created = True
            connection.execute(
                text(
                    f"CREATE TABLE {schema}.chapters (run_id text, chapter_id integer,"
                    " PRIMARY KEY (run_id, chapter_id))"
                )
            )
            connection.execute(text(f"INSERT INTO {schema}.chapters VALUES ('old-run', 1)"))
        legacy_engine = engine.execution_options(schema_translate_map={None: schema})
        with pytest.raises(RuntimeError, match="从原始输入重建"):
            validate_existing_schema(legacy_engine)
        assert inspect(engine).get_pk_constraint("chapters", schema=schema)["constrained_columns"] == [
            "run_id",
            "chapter_id",
        ]
        with engine.connect() as connection:
            row = connection.execute(text(f"SELECT run_id, chapter_id FROM {schema}.chapters")).one()
            assert row.run_id == "old-run"
            assert row.chapter_id == 1
    finally:
        if created:
            with engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))


@pytest.mark.asyncio
async def test_embedding_preparation_reads_plain_records_without_storage_context(prepared_chapter, monkeypatch):
    from src.workflows import preprocess

    storage, run_id, text_value = prepared_chapter
    monkeypatch.setattr(preprocess, "get_storage_factory", lambda: lambda: storage)

    class Embeddings:
        async def embed_texts(self, texts, progress_callback):
            assert texts == [text_value]
            await progress_callback(1, 1, 1)
            return [[0.1, 0.2]]

    rows = await preprocess._generate_paragraph_embedding_rows(Embeddings(), run_id, SimpleNamespace)
    assert len(rows) == 1
    assert rows[0].paragraph_id == 1
    assert rows[0].embedding_vector == [0.1, 0.2]
