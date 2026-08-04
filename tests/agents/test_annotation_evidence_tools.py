"""
标注 Agent 三层证据工具与审计账本回归测试
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.annotation.evidence import AnnotationEvidenceLedger
from src.agents.annotation.graph import build_annotation_graph
from src.agents.annotation.memory import IdentityMemory
from src.agents.annotation.runner import (
    AnnotationAgentRunError,
    _record_annotation_interaction,
    run_annotation_agent,
)
from src.agents.annotation.tools import build_annotation_tools
from src.rag.evidence_types import EvidenceBundle, EvidenceItem
from src.rag.retriever import NarrativeEvidenceService
from src.storage.repositories.chunk import KeywordMatchRow


def _find_tool(tools: list, name: str):
    """
    2026-08-02 用于按名称取得标注 Agent 工具测试对象
    """
    return next(candidate for candidate in tools if candidate.name == name)


def _semantic_item() -> EvidenceItem:
    """
    2026-08-02 用于构造带稳定 ID 的历史自然段证据测试数据
    """
    return EvidenceItem(
        evidence_type="semantic_recall",
        source="paragraph_embeddings",
        content="阿顾摘下面具，露出顾霜的面容。",
        evidence_id="paragraph:3:1:120:137",
        metadata={
            "paragraph_index": 1,
            "global_start_char": 120,
            "global_end_char": 137,
        },
        chunk_id=3,
        score=0.93,
        retrieval_method="semantic",
    )


@pytest.mark.asyncio
async def test_authority_tool_requests_only_level1_and_renders_filtered_items() -> None:
    """
    2026-08-02 用于锁定 Level1 工具只消费请求裁剪后的结构化事实
    """
    service = MagicMock()
    service.collect = AsyncMock(
        return_value=EvidenceBundle(
            structured_evidence=[
                EvidenceItem(
                    evidence_type="alias_mapping",
                    source="graph_alias_map",
                    content="阿顾 -> 顾霜",
                )
            ]
        )
    )
    tools = build_annotation_tools(
        service,
        IdentityMemory(known_canonical_names={"顾霜", "无关人物"}),
        run_id="run-1",
        chunk_id=8,
    )

    rendered = await _find_tool(tools, "lookup_authority_facts").ainvoke(
        {"names": ["阿顾"], "objective": "identity"}
    )

    request = service.collect.await_args.args[0]
    assert request.requested_names == ["阿顾"]
    assert request.need_level1 is True
    assert request.need_level2 is False
    assert request.mode is None
    assert "阿顾 -> 顾霜" in rendered
    assert "无关人物" not in rendered


@pytest.mark.asyncio
async def test_evidence_tools_read_identity_memory_at_call_time() -> None:
    """
    2026-08-02 用于保证注册新身份后后续证据请求读取最新会话记忆
    """
    service = MagicMock()
    service.collect = AsyncMock(return_value=EvidenceBundle())
    memory = IdentityMemory()
    tools = build_annotation_tools(
        service,
        memory,
        run_id="run-1",
        chunk_id=8,
    )
    _find_tool(tools, "register_identity").invoke(
        {
            "name": "阿顾",
            "canonical": "顾霜",
            "entity_type": "character",
            "evidence": "阿顾摘下面具",
        }
    )

    await _find_tool(tools, "lookup_authority_facts").ainvoke(
        {"names": ["阿顾"], "objective": "identity"}
    )

    request = service.collect.await_args.args[0]
    assert request.background_entities == ["顾霜"]


@pytest.mark.asyncio
async def test_paragraph_tool_returns_evidence_ids_and_records_audit_ledger() -> None:
    """
    2026-08-02 用于验证 Level3 工具返回稳定证据 ID 并登记调用账本
    """
    service = MagicMock()
    service.collect = AsyncMock(
        return_value=EvidenceBundle(historical_evidence=[_semantic_item()])
    )
    ledger = AnnotationEvidenceLedger()
    tools = build_annotation_tools(
        service,
        IdentityMemory(),
        run_id="run-1",
        chunk_id=8,
        evidence_ledger=ledger,
    )

    rendered = await _find_tool(tools, "search_paragraph_evidence").ainvoke(
        {"query": "阿顾是谁", "objective": "identity", "top_k": 4}
    )

    request = service.collect.await_args.args[0]
    assert request.need_level1 is False
    assert request.need_level2 is False
    assert request.mode == "semantic"
    assert request.historical_max_chunk_id() == 7
    assert "evidence_id=paragraph:3:1:120:137" in rendered
    assert set(ledger.entries) == {"paragraph:3:1:120:137"}
    assert ledger.tool_calls[-1].status == "success"
    assert ledger.tool_calls[-1].evidence_ids == ["paragraph:3:1:120:137"]


@pytest.mark.asyncio
async def test_paragraph_tool_propagates_required_level3_failure() -> None:
    """
    2026-08-02 用于保证 Level3 必需性故障不会降级为普通工具文本
    """
    service = MagicMock()
    service.collect = AsyncMock(
        side_effect=RuntimeError("Level 3 paragraph retrieval is required but not available")
    )
    ledger = AnnotationEvidenceLedger()
    tools = build_annotation_tools(
        service,
        IdentityMemory(),
        run_id="run-1",
        chunk_id=8,
        evidence_ledger=ledger,
    )

    with pytest.raises(RuntimeError, match="required but not available"):
        await _find_tool(tools, "search_paragraph_evidence").ainvoke(
            {"query": "阿顾是谁", "objective": "identity", "top_k": 5}
        )

    assert ledger.tool_calls[-1].status == "error"
    assert "required but not available" in str(ledger.tool_calls[-1].error)


@pytest.mark.asyncio
async def test_annotation_graph_does_not_absorb_evidence_tool_failure() -> None:
    """
    2026-08-02 用于验证标注图关闭 ToolNode 自动异常文本包装
    """
    service = MagicMock()
    service.collect = AsyncMock(side_effect=RuntimeError("required Level3 failed"))
    tools = build_annotation_tools(
        service,
        IdentityMemory(),
        run_id="run-1",
        chunk_id=8,
    )

    class _SearchEvidenceLLM:
        """只调用一次历史证据工具的测试模型"""

        def bind_tools(self, _tools):
            """
            2026-08-02 用于返回测试模型自身以模拟工具绑定
            """
            return self

        async def ainvoke(self, _messages):
            """
            2026-08-02 用于生成会触发 Level3 故障的工具调用
            """
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_paragraph_evidence",
                        "args": {
                            "query": "阿顾是谁",
                            "objective": "identity",
                            "top_k": 5,
                        },
                        "id": "call-search-1",
                        "type": "tool_call",
                    }
                ],
            )

    graph = build_annotation_graph(_SearchEvidenceLLM(), tools)

    with pytest.raises(RuntimeError, match="required Level3 failed"):
        await graph.ainvoke(
            {
                "messages": [
                    SystemMessage(content="test"),
                    HumanMessage(content="标注当前文本"),
                ],
                "attempts": 0,
                "output": None,
                "error": None,
            }
        )


def test_annotation_interaction_records_tool_messages_and_evidence_audit() -> None:
    """
    2026-08-02 用于验证现有模型交互表承载完整工具消息与证据审计账本
    """
    ledger = AnnotationEvidenceLedger()
    ledger.register_evidence_items([_semantic_item()], objective="identity")
    ledger.record_tool_call(
        tool_name="search_paragraph_evidence",
        objective="identity",
        request={"query": "阿顾是谁", "top_k": 5},
        status="success",
        evidence_ids=["paragraph:3:1:120:137"],
        duration_ms=12,
    )
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_paragraph_evidence",
                    "args": {
                        "query": "阿顾是谁",
                        "objective": "identity",
                        "top_k": 5,
                    },
                    "id": "call-search-1",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content="[evidence_id=paragraph:3:1:120:137] 阿顾摘下面具",
            tool_call_id="call-search-1",
            name="search_paragraph_evidence",
        ),
    ]
    llm = MagicMock(model_name="annotation-test")
    llm.base_url = "http://localhost:1234/v1"

    with pytest.MonkeyPatch.context() as monkeypatch:
        mock_record = MagicMock()
        monkeypatch.setattr(
            "src.models.interactions.record_model_interaction",
            mock_record,
        )
        _record_annotation_interaction(
            session=object(),
            run_id="run-1",
            novel_id="novel-1",
            chunk_id=8,
            llm=llm,
            messages=messages,
            raw_output={"chunk_summary": "顾霜确认身份"},
            evidence_ledger=ledger,
            elapsed=0.25,
        )

    kwargs = mock_record.call_args.kwargs
    assert len(kwargs["messages"]) == 3
    assert "tool_calls" in kwargs["messages"][0]["content"]
    assert kwargs["messages"][-1]["role"] == "evidence_audit"
    evidence_audit = json.loads(kwargs["messages"][-1]["content"])
    assert evidence_audit["historical_evidence"][0]["evidence_id"] == "paragraph:3:1:120:137"
    assert evidence_audit["tool_calls"][0]["status"] == "success"
    assert json.loads(kwargs["response_text"]) == {"chunk_summary": "顾霜确认身份"}


def test_record_annotation_interaction_records_each_agent_response() -> None:
    """
    2026-08-04 用于保证多轮取证和 finish 各自形成模型调用审计记录
    """
    ledger = AnnotationEvidenceLedger()
    messages = [
        AIMessage(content="先取证"),
        AIMessage(content="再完成"),
    ]
    llm = MagicMock(model_name="annotation-test")
    llm.base_url = "http://localhost:1234/v1"

    with pytest.MonkeyPatch.context() as monkeypatch:
        mock_record = MagicMock()
        monkeypatch.setattr("src.models.interactions.record_model_interaction", mock_record)
        _record_annotation_interaction(
            session=object(),
            run_id="run-1",
            novel_id="novel-1",
            chunk_id=8,
            llm=llm,
            messages=messages,
            raw_output={"chunk_summary": "完成"},
            evidence_ledger=ledger,
            elapsed=0.25,
        )

    assert mock_record.call_count == 2
    assert [call.kwargs["attempt_number"] for call in mock_record.call_args_list] == [1, 2]


def test_evidence_ledger_merges_keyword_and_semantic_sources_for_one_paragraph() -> None:
    """
    2026-08-03 用于验证同一稳定段落证据合并多种取证来源和匹配信息
    """
    ledger = AnnotationEvidenceLedger()
    evidence_id = "paragraph:3:1:120:138"
    ledger.register_evidence_items(
        [
            EvidenceItem(
                evidence_type="keyword_recall",
                source="chunks.text",
                content="顾霜摘下面具，众人认出她就是阿顾。",
                evidence_id=evidence_id,
                metadata={
                    "paragraph_index": 1,
                    "global_start_char": 120,
                    "global_end_char": 138,
                    "matched_keywords": ["顾霜", "阿顾"],
                    "match_count": 2,
                },
                chunk_id=3,
                retrieval_method="keyword",
            )
        ],
        objective="identity",
    )
    ledger.register_evidence_items(
        [
            EvidenceItem(
                evidence_type="semantic_recall",
                source="paragraph_embeddings",
                content="顾霜摘下面具，众人认出她就是阿顾。",
                evidence_id=evidence_id,
                metadata={
                    "paragraph_index": 1,
                    "global_start_char": 120,
                    "global_end_char": 138,
                },
                chunk_id=3,
                score=0.91,
                retrieval_method="semantic",
            )
        ],
        objective="relation",
    )

    entry = ledger.entries[evidence_id]
    assert entry.retrieval_methods == ["keyword", "semantic"]
    assert entry.sources == ["chunks.text", "paragraph_embeddings"]
    assert entry.objectives == ["identity", "relation"]
    assert entry.matched_keywords == ["顾霜", "阿顾"]
    assert entry.match_count == 2


def test_keyword_search_registers_paragraph_evidence_ids() -> None:
    """
    2026-08-02 用于把关键词精确检索纳入同一历史原文证据账本
    """
    ledger = AnnotationEvidenceLedger()
    service = NarrativeEvidenceService(
        run_id="run-1",
        session=MagicMock(),
        level3_enabled=False,
    )
    tools = build_annotation_tools(
        service,
        IdentityMemory(),
        run_id="run-1",
        chunk_id=8,
        session=MagicMock(),
        evidence_ledger=ledger,
    )
    match = KeywordMatchRow(
        chunk_id=3,
        paragraph_index=2,
        paragraph_text="众人一直称顾霜为阿顾。",
        local_start_char=20,
        local_end_char=32,
        global_start_char=200,
        global_end_char=212,
        matched_keywords=("顾霜", "阿顾"),
        match_count=2,
    )

    with patch(
        "src.storage.repositories.chunk.search_paragraphs_by_keywords",
        return_value=[match],
    ):
        rendered = _find_tool(tools, "search_paragraph_by_keywords").ainvoke(
            {
                "keywords": "顾霜 阿顾",
                "objective": "identity",
                "top_k": 5,
            }
        )
        rendered = asyncio.run(rendered)

    evidence_id = "paragraph:3:2:200:212"
    assert f"evidence_id={evidence_id}" in rendered
    assert ledger.entries[evidence_id].evidence_type == "keyword_recall"
    assert ledger.tool_calls[-1].evidence_ids == [evidence_id]


def test_read_chunk_blocks_current_or_future_content() -> None:
    """
    2026-08-02 用于保证历史原文展开工具不能读取当前或未来 chunk
    """
    ledger = AnnotationEvidenceLedger()
    service = NarrativeEvidenceService(
        run_id="run-1",
        session=MagicMock(),
        level3_enabled=False,
    )
    tools = build_annotation_tools(
        service,
        IdentityMemory(),
        run_id="run-1",
        chunk_id=8,
        session=MagicMock(),
        evidence_ledger=ledger,
    )

    with patch("src.storage.repositories.chunk.fetch_chunk_text") as mock_fetch:
        rendered = asyncio.run(_find_tool(tools, "read_chunk").ainvoke(
            {"chunk_id_to_read": 8, "objective": "identity"}
        ))

    assert "位于当前 chunk 之前" in rendered
    assert ledger.tool_calls[-1].status == "blocked_by_policy"
    mock_fetch.assert_not_called()


def test_read_chunk_blocks_unlocated_historical_content() -> None:
    """
    2026-08-02 用于阻止 Agent 通过猜测 chunk 编号扫描未定位的历史原文
    """
    ledger = AnnotationEvidenceLedger()
    service = NarrativeEvidenceService(
        run_id="run-1",
        session=MagicMock(),
        level3_enabled=False,
    )
    tools = build_annotation_tools(
        service,
        IdentityMemory(),
        run_id="run-1",
        chunk_id=8,
        session=MagicMock(),
        evidence_ledger=ledger,
    )

    with patch("src.storage.repositories.chunk.fetch_chunk_text") as mock_fetch:
        rendered = asyncio.run(_find_tool(tools, "read_chunk").ainvoke(
            {"chunk_id_to_read": 3, "objective": "identity"}
        ))

    assert "同一检索目标已经定位" in rendered
    assert ledger.tool_calls[-1].status == "blocked_by_policy"
    mock_fetch.assert_not_called()


def test_read_chunk_blocks_objective_laundering() -> None:
    """
    2026-08-02 用于阻止 Agent 把身份检索定位的 chunk 改标为关系证据
    """
    ledger = AnnotationEvidenceLedger()
    service = NarrativeEvidenceService(
        run_id="run-1",
        session=MagicMock(),
        level3_enabled=False,
    )
    service._historical_authorizations[("annotation_agent", "identity", 8)] = {3}
    tools = build_annotation_tools(
        service,
        IdentityMemory(),
        run_id="run-1",
        chunk_id=8,
        session=MagicMock(),
        evidence_ledger=ledger,
    )

    with patch("src.storage.repositories.chunk.fetch_chunk_text") as mock_fetch:
        rendered = asyncio.run(_find_tool(tools, "read_chunk").ainvoke(
            {"chunk_id_to_read": 3, "objective": "relation"}
        ))

    assert "同一检索目标已经定位" in rendered
    assert ledger.tool_calls[-1].status == "blocked_by_policy"
    mock_fetch.assert_not_called()


def test_read_chunk_registers_historical_source_evidence() -> None:
    """
    2026-08-02 用于把受限历史 chunk 展开结果登记为可审计证据
    """
    ledger = AnnotationEvidenceLedger()
    service = NarrativeEvidenceService(
        run_id="run-1",
        session=MagicMock(),
        level3_enabled=False,
    )
    service._historical_authorizations[("annotation_agent", "identity", 8)] = {3}
    tools = build_annotation_tools(
        service,
        IdentityMemory(),
        run_id="run-1",
        chunk_id=8,
        session=MagicMock(),
        evidence_ledger=ledger,
    )

    with patch(
        "src.storage.repositories.chunk.fetch_chunk_text",
        return_value="顾霜摘下面具，众人认出她就是阿顾。",
    ):
        rendered = asyncio.run(_find_tool(tools, "read_chunk").ainvoke(
            {"chunk_id_to_read": 3, "objective": "identity"}
        ))

    assert "evidence_id=chunk:3" in rendered
    assert ledger.entries["chunk:3"].evidence_type == "historical_chunk_read"
    assert ledger.tool_calls[-1].status == "success"


@pytest.mark.asyncio
async def test_annotation_agent_records_failed_tool_run_before_raising() -> None:
    """
    2026-08-02 用于保证证据工具故障任务也写入 error 交互审计记录
    """
    graph = MagicMock()
    graph.ainvoke = AsyncMock(side_effect=RuntimeError("required Level3 failed"))
    llm = MagicMock()
    llm.model_name = "annotation-test"
    llm.base_url = "http://localhost:1234/v1"

    with (
        patch("src.agents.annotation.runner.build_annotation_graph", return_value=graph),
        patch("src.models.interactions.record_model_interaction") as mock_record,
    ):
        with pytest.raises(AnnotationAgentRunError, match="required Level3 failed"):
            await run_annotation_agent(
                chunk_text="顾霜进入山门。",
                chunk_id=8,
                total_chunks=10,
                novel_id="novel-1",
                memory=IdentityMemory(),
                llm=llm,
                run_id="run-1",
                session=object(),
            )

    kwargs = mock_record.call_args.kwargs
    assert kwargs["status"] == "error"
    assert kwargs["error_message"] == "required Level3 failed"
    response_payload = json.loads(kwargs["response_text"])
    assert response_payload["error"] == "required Level3 failed"
    evidence_audit = json.loads(kwargs["messages"][-1]["content"])
    assert evidence_audit["tool_calls"] == []
