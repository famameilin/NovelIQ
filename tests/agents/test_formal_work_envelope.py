"""正式工作信封的工具权限与未来原文来源标签"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.annotation.schema import TextSearchResult
from src.agents.annotation.tools import AnnotationToolLedger
from src.fact_graph.graph import FactGraph
from tests.support.annotation_work_tools import build_annotation_tools


def _formal_tools():
    query_service = MagicMock()
    ledger = AnnotationToolLedger(
        run_scope="run-1",
        current_chapter_id=1,
        current_chapter_text="第一章原文。",
        allow_future_context=True,
        graph=FactGraph(run_scope="run-1:1"),
    )
    return ledger, query_service, {item.name: item for item in build_annotation_tools(query_service, ledger)}




@pytest.mark.asyncio
async def test_future_text_search_has_auditable_source_capability() -> None:
    _ledger, query_service, tools = _formal_tools()
    query_service.search_text = AsyncMock(
        return_value=[
            TextSearchResult(
                chapter_id=8, paragraph_ids=[80], content="第八章证实身份",
                keyword_score=1.0,
            )
        ]
    )
    result = json.loads(await tools["search_text"].ainvoke({"query": "身份"}))
    assert result[0]["chapter_id"] == 8
    assert result[0]["paragraph_ids"] == [80]
    assert result[0]["capability"] == "other_text"
    query_service.search_text.assert_awaited_once_with("身份", range_name="all", limit=9)
