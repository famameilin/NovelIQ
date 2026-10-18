"""诊断简洁索引与实际包含端点，不改变原文绑定和业务写入校验

夹具自足：真实标注来源链直接写入章级声明（event_declarations + 证据/参与者关系行），
读取面经 build_diagnosis_tools 的真实工具原形。
"""

from __future__ import annotations

import json

import pytest

from src.agents.diagnosis.tools import build_diagnosis_tools
from src.event_trees.organization import EventOrganizationDraft, OrganizationEvidence
from src.storage import new_id
from src.storage.models import DeclarationParticipant
from tests.agents.test_diagnosis_organization import organization_case as organization_case
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import (
    add_annotation_source,
    add_declaration,
    add_diagnosis_context,
    close_structure,
    ensure_character,
    first_paragraph,
    identity_every_declaration,
    publish_draft,
    report_case_anchor,
)
from tests.support.storage_fixtures import fixture_id, natural_record, storage_for

LONG_SUMMARY = "顾霜寻路并点灯。" * 200


@pytest.fixture
def declaration_case(db_session):
    """两章级声明的真实来源链与本模块草稿（同章两段声明，各带原文证据）"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜寻路并点灯。"])
    session_id, execution_id = add_diagnosis_context(db_session, run_id)
    record_id, _source_execution = add_annotation_source(db_session, run_id, 1, role="event")
    paragraph = first_paragraph(db_session, run_id)
    add_declaration(
        db_session,
        record_id=record_id,
        paragraph=paragraph,
        phrase="寻路",
        title="寻路",
        problem="能否找到路",
        summary=LONG_SUMMARY,
        event_type="寻路",
        participants=(("顾霜", "主体"),),
    )
    add_declaration(
        db_session,
        record_id=record_id,
        paragraph=paragraph,
        phrase="点灯",
        title="点灯",
        problem="能否照明",
        summary="顾霜点灯",
        event_type="照明",
        status="resolved",
    )
    db_session.commit()
    draft = EventOrganizationDraft(storage_for(db_session), run_id, session_id)
    draft.fixture_session = db_session
    draft.case_id = report_case_anchor(run_id)
    draft.producer_invocation_id = execution_id
    return draft


def test_declaration_index_keeps_paragraphs_and_detail_keeps_full_source(declaration_case):
    draft = declaration_case
    identifiers = list(draft._declarations())
    paragraph_id = first_paragraph(draft.fixture_session, draft.run_id).paragraph_id
    # 参与者是正式关系行：索引不携带无界人物列表，详情完整保留全部来源
    draft.fixture_session.add(
        DeclarationParticipant(
            participant_id=new_id(),
            declaration_id=identifiers[0],
            participant_ordinal=1,
            entity_id=ensure_character(draft.fixture_session, run_id=draft.run_id, name="贺重明"),
            role="旁观",
            action="寻路" * 80,
        )
    )
    draft.fixture_session.flush()
    tools = {
        tool.name: tool
        for tool in build_diagnosis_tools(
            storage_for(draft.fixture_session),
            draft.run_id,
            organization_draft=draft,
            execution_id=fixture_id(__name__, "read-surface"),
        )
    }
    first = json.loads(tools["search_events"].invoke({"limit": 1}))
    assert first["total"] == 2 and first["next_offset"] == 1
    indexed = first["events"][0]
    assert indexed["declaration_id"] == identifiers[0]
    assert "participants" not in indexed
    assert indexed["evidence"] == [{"paragraph_id": paragraph_id}]
    assert len(indexed["summary"]) <= 160
    second = json.loads(tools["search_events"].invoke({"offset": first["next_offset"], "limit": 1}))
    assert second["next_offset"] is None and second["events"][0]["declaration_id"] == identifiers[1]
    detail = json.loads(tools["read_event"].invoke({"node_id": identifiers[0]}))["content"]
    assert detail["summary"] == LONG_SUMMARY
    assert [item["action"] for item in detail["participants"]] == [None, "寻路" * 80]
    assert detail["evidence"] == draft._declarations()[identifiers[0]]["evidence"]
    assert len(json.dumps(indexed)) < len(json.dumps(detail)) / 10
    # 读取不改变已保存声明关系
    assert draft._declarations()[identifiers[0]]["participants"] == detail["participants"]
    # 索引段号仍经正式原文绑定，不借简洁读取绕过证据校验
    source_evidence = draft._declarations()[identifiers[0]]["evidence"][0]
    assert indexed["evidence"][0]["paragraph_id"] == source_evidence["paragraph_id"]
    bound = draft.bind_evidence([OrganizationEvidence(paragraph_id=source_evidence["paragraph_id"], quote="寻路")])[0]
    assert (bound.char_start, bound.char_end, bound.text_hash) == (
        source_evidence["char_start"],
        source_evidence["char_end"],
        source_evidence["text_hash"],
    )
    with pytest.raises(ValueError, match="声明引用不属于本 run"):
        tools["read_event"].invoke({"node_id": "unknown-process"})
    with pytest.raises(ValueError, match="每页最多 20 条"):
        tools["search_events"].invoke({"limit": 21})


def test_saved_nested_event_read_and_rejection_identify_actual_top_level(db_session, organization_case):
    case, event_ids, draft = organization_case
    root, child, parent = event_ids[0], event_ids[1], event_ids[2]
    # 链为 root→parent→child：读取与拒绝都必须给出实际端点
    draft.contain(
        parent_event_id=parent,
        child_event_id=child,
        reason="原文中的父级问题",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    close_structure(db_session, draft, evidence_paragraph_id=0)
    publish_draft(db_session, case.run_id, draft)
    fresh = EventOrganizationDraft(storage_for(db_session), case.run_id, case.session_id)
    fresh.fixture_session = db_session
    fresh.case_id = report_case_anchor(case.run_id)
    fresh.producer_invocation_id = case.execution_id
    tools = {
        tool.name: tool
        for tool in build_diagnosis_tools(
            storage_for(db_session),
            case.run_id,
            role="report",
            organization_draft=fresh,
            execution_id=fixture_id(__name__, "read-hierarchy"),
        )
    }
    detail = json.loads(tools["read_event"].invoke({"node_id": child, "kind": "event"}))
    assert detail["parent_event_id"] == parent
    assert detail["top_level_event_id"] == root and detail["is_top_level"] is False
    page = json.loads(tools["search_events"].invoke({"kind": "event"}))
    assert page["total"] == 3
    roots = [item for item in page["events"] if item["is_top_level"]]
    assert len(roots) == 1 and roots[0]["event_id"] == root
    assert roots[0]["is_top_level"] is True
    assert roots[0]["parent_event_id"] is None
    outcome = fresh.register_outcome(
        key="result",
        title="身份结果",
        description="身份得到确认",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    rejected = json.loads(
        tools["write_outcome"].invoke(
            {
                "items": [
                    {
                        "operation": "link",
                        "event_id": child,
                        "outcome_id": outcome,
                        "reason": "子问题形成结果",
                        "evidence": [{"paragraph_id": 0}],
                    }
                ]
            }
        )
    )
    assert rejected["status"] == "partial"
    assert f"parent_event_id={parent}" in rejected["failed"][0]["message"]
    assert f"top_level_event_id={root}" in rejected["failed"][0]["message"]
    assert not fresh.event_outcome_links
    assert child not in fresh.reviewed_events and root not in fresh.reviewed_events
    tools["write_outcome"].invoke(
        {
            "items": [
                {
                    "operation": "link",
                    "event_id": root,
                    "outcome_id": outcome,
                    "reason": "核对顶层问题的贡献",
                    "evidence": [{"paragraph_id": 0}],
                }
            ]
        }
    )
    assert set(fresh.event_outcome_links) == {(root, outcome)}


def test_draft_parent_change_is_reflected_in_reads_without_rewriting_child(declaration_case):
    draft = declaration_case
    draft, _meta = identity_every_declaration(draft.fixture_session, draft.run_id)
    child, parent = list(draft.events)
    assert draft.read_events([child])[0]["is_top_level"] is True
    before = draft.events[child].model_dump(mode="json")
    draft.contain(
        parent_event_id=parent,
        child_event_id=child,
        reason="父级问题明确包含子问题",
        evidence=[OrganizationEvidence(paragraph_id=0)],
    )
    detail = draft.read_events([child])[0]
    assert detail["parent_event_id"] == detail["top_level_event_id"] == parent
    assert detail["is_top_level"] is False
    assert draft.search_events(top_level_only=True)["items"][0]["event_id"] == parent
    assert draft.events[child].model_dump(mode="json") == before


async def test_shared_text_reader_binds_exact_original_and_rejects_unmatched_occurrence(declaration_case):
    from src.agents.annotation.errors import AnnotationInputError
    from src.agents.annotation.text_search import TextSearchService
    from src.storage.models import Paragraph
    from src.utils.identity import text_digest

    draft = declaration_case
    row = natural_record(draft.fixture_session, Paragraph, {"run_id": draft.run_id, "paragraph_id": 0})
    quote = row.text[:2]
    tools = {
        item.name: item
        for item in build_diagnosis_tools(
            storage_for(draft.fixture_session),
            draft.run_id,
            organization_draft=draft,
            text_search=TextSearchService(
                storage_for(draft.fixture_session), run_id=draft.run_id, semantic_enabled=False
            ),
        )
    }
    result = json.loads(await tools["read_text"].ainvoke({"paragraph_id": 0, "quote": quote}))
    assert result["content"] == quote and result["source_ref"]
    assert result["paragraph_id"] == row.paragraph_id and result["chapter_id"] == row.chapter_id
    assert result["text_hash"] == text_digest(quote)
    assert row.text[result["char_start"] : result["char_end"]] == quote
    with pytest.raises(AnnotationInputError, match="不匹配原文"):
        await tools["read_text"].ainvoke({"paragraph_id": 0, "quote": quote, "occurrence": 100})
    with pytest.raises(ValueError, match="不属于本 run"):
        await tools["read_text"].ainvoke({"paragraph_id": 100000})
    hits = json.loads(await tools["search_text"].ainvoke({"query": quote}))
    assert any(row.paragraph_id in hit["paragraph_ids"] for hit in hits)


async def test_shared_search_embedding_failure_stops_program_before_later_operation(declaration_case):
    from unittest.mock import AsyncMock, MagicMock

    from src.agents.annotation.text_search import TextSearchService
    from src.agents.diagnosis.program_runtime import DiagnosisProgramDependencyError, DiagnosisProgramRuntime
    from src.embedding import EmbeddingConnectionError

    draft = declaration_case
    client = MagicMock()
    client.get_embedding = AsyncMock(side_effect=EmbeddingConnectionError("embedding unavailable"))
    observer = MagicMock()
    runtime = DiagnosisProgramRuntime(
        build_diagnosis_tools(
            storage_for(draft.fixture_session),
            draft.run_id,
            role="report",
            organization_draft=draft,
            text_search=TextSearchService(
                storage_for(draft.fixture_session), run_id=draft.run_id, embedding_client=client
            ),
        ),
        observer=observer,
    )
    with pytest.raises(DiagnosisProgramDependencyError, match="embedding unavailable"):
        await runtime.execute('search_text(query="寻路")\nread_topics()')
    rows = [item.kwargs for item in observer.record_tool_call.call_args_list]
    assert len(rows) == 1 and rows[0]["tool_name"] == "search_text" and rows[0]["status"] == "error"


async def test_shared_text_argument_rejection_remains_repairable_in_same_program(declaration_case):
    from src.agents.diagnosis.program_runtime import DiagnosisProgramRuntime

    draft = declaration_case
    runtime = DiagnosisProgramRuntime(
        build_diagnosis_tools(storage_for(draft.fixture_session), draft.run_id, organization_draft=draft)
    )
    result = json.loads(
        await runtime.execute(
            'bad = read_text(paragraph_id=0, quote="不存在于原文的引文")\ngood = read_text(paragraph_id=0)'
        )
    )
    assert result["status"] == "partial" and len(result["failed"]) == 1
    assert runtime.env["bad"] is None
    assert runtime.env["good"]["paragraph_id"] == 0 and runtime.env["good"]["source_ref"]


def test_diagnosis_reads_survive_interrupted_pipeline_commit(declaration_case, monkeypatch):
    """管线会话提交被打断（PREPARED 中间态）时，诊断读取必须照常工作

    诊断域曾与管线会话共用；管线会话被流式 emitter
    持续 commit，一次提交中途被打断留在 PREPARED 后，read_event 的声明读取抛
    "This session is in 'prepared' state" 并被伪装成工具依赖故障。诊断域必须经
    open_diagnosis_session 独立成会话：开工先提交管线会话，此后读写与发布不依赖
    管线会话的事务状态。
    """
    from sqlalchemy import text
    from sqlalchemy.exc import InvalidRequestError

    from src.agents.diagnosis import domain as domain_module
    from src.agents.diagnosis.runner import open_diagnosis_session
    from src.config import settings
    from src.config.schemas.model import WeightedModelSettings

    draft = declaration_case
    pipeline = draft.fixture_session
    monkeypatch.setattr(
        settings.models,
        "model_pool",
        [WeightedModelSettings("read-surface-model", "https://read.example/v1", "read-key")],
    )
    monkeypatch.setattr(settings.models, "diagnosis_model_id", "read-surface-model")
    from sqlalchemy.orm import sessionmaker

    from src.storage import Storage
    from src.storage.operations import OperationRunner

    domain_session = open_diagnosis_session(Storage(_runner=OperationRunner(sessionmaker(bind=pipeline.get_bind()))))
    domain = domain_module.create_diagnosis_domain(
        session=storage_for(domain_session),
        run_id=draft.run_id,
        novel_id=fixture_id(__name__, "test-novel"),
        execution_id=fixture_id(__name__, "interrupted-pipeline-commit"),
        novel_title=None,
    )
    try:
        # 复现"提交中途被打断"的现场形态：管线会话停在 PREPARED，此后任意 SQL 全灭
        pipeline.execute(text("SELECT 1"))
        pipeline.get_transaction()._prepare_impl()
        with pytest.raises(InvalidRequestError, match="prepared"):
            pipeline.execute(text("SELECT 1"))
        # 修复契约：诊断读取不依赖管线会话
        source = next(iter(domain.sources))
        row = domain.draft.read_declarations([source])["items"][0]
        assert row["declaration_id"] == source
        # 反向对照：同一次声明读取走旧接线（draft 挂在管线会话上）必被中间态拒绝
        with pytest.raises(InvalidRequestError, match="prepared"):
            draft.read_declarations([source])
    finally:
        domain.close()
        pipeline.rollback()
