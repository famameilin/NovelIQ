"""
统一历史取证服务回归测试
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.rag.evidence_contracts import EvidenceRequest
from src.rag.level3_vector import Level3NotReadyError
from src.rag.retriever import NarrativeEvidenceService
from src.storage.repositories.chunk import KeywordMatchRow


def _keyword_match() -> KeywordMatchRow:
    """
    2026-08-03 用于构造关键词历史自然段测试结果
    """
    return KeywordMatchRow(
        chunk_id=3,
        paragraph_index=1,
        paragraph_text="顾霜摘下面具，众人认出她就是阿顾。",
        local_start_char=20,
        local_end_char=38,
        global_start_char=120,
        global_end_char=138,
        matched_keywords=("顾霜", "阿顾"),
        match_count=2,
    )


@pytest.mark.asyncio
async def test_keyword_mode_uses_chunks_text_without_semantic_readiness() -> None:
    """
    2026-08-03 用于验证关键词取证不依赖 paragraph embedding readiness
    """
    service = NarrativeEvidenceService(
        run_id="run-1",
        session=MagicMock(),
        embedding_client=None,
        level3_enabled=True,
    )
    service._level3.ensure_level3_ready = AsyncMock()

    with patch(
        "src.storage.repositories.chunk.search_paragraphs_by_keywords",
        return_value=[_keyword_match()],
    ) as search:
        bundle = await service.collect(
            EvidenceRequest(
                consumer="annotation_agent",
                objective="identity",
                mode="keyword",
                keywords=["顾霜", "阿顾"],
                current_chunk=8,
                top_k=5,
            )
        )

    item = bundle.historical_evidence[0]
    assert item.retrieval_method == "keyword"
    assert item.source == "chunks.text"
    assert item.evidence_id == "paragraph:3:1:120:138"
    assert item.metadata["local_start_char"] == 20
    assert item.metadata["global_start_char"] == 120
    assert item.metadata["matched_keywords"] == ["顾霜", "阿顾"]
    assert bundle.generation_meta["semantic_executed"] is False
    service._level3.ensure_level3_ready.assert_not_awaited()
    call_kwargs = search.call_args.kwargs
    assert call_kwargs["max_chunk_id"] == 7
    assert call_kwargs["exclude_chunk_ids"] == [8]


@pytest.mark.asyncio
async def test_read_mode_requires_same_objective_location_and_history_boundary() -> None:
    """
    2026-08-03 用于验证 read 只读取同一 objective 已定位的历史 chunk
    """
    service = NarrativeEvidenceService(
        run_id="run-1",
        session=MagicMock(),
        embedding_client=None,
        level3_enabled=True,
    )
    service._level3.ensure_level3_ready = AsyncMock()

    with patch(
        "src.storage.repositories.chunk.search_paragraphs_by_keywords",
        return_value=[_keyword_match()],
    ):
        await service.collect(
            EvidenceRequest(
                consumer="annotation_agent",
                objective="identity",
                mode="keyword",
                keywords=["顾霜"],
                current_chunk=8,
                top_k=5,
            )
        )

    with patch(
        "src.storage.repositories.chunk.fetch_chunk_text",
        return_value="顾霜摘下面具，众人认出她就是阿顾。",
    ) as fetch:
        authorized = await service.collect(
            EvidenceRequest(
                consumer="annotation_agent",
                objective="identity",
                mode="read",
                read_chunk_id=3,
                current_chunk=8,
            )
        )

    assert authorized.generation_meta["read_status"] == "success"
    assert authorized.historical_evidence[0].retrieval_method == "read"
    assert authorized.historical_evidence[0].evidence_id == "chunk:3"
    fetch.assert_called_once_with(service._session, "run-1", 3)
    service._level3.ensure_level3_ready.assert_not_awaited()

    current = await service.collect(
        EvidenceRequest(
            consumer="annotation_agent",
            objective="identity",
            mode="read",
            read_chunk_id=8,
            current_chunk=8,
        )
    )
    future = await service.collect(
        EvidenceRequest(
            consumer="annotation_agent",
            objective="identity",
            mode="read",
            read_chunk_id=9,
            current_chunk=8,
        )
    )
    mismatched_objective = await service.collect(
        EvidenceRequest(
            consumer="annotation_agent",
            objective="relation",
            mode="read",
            read_chunk_id=3,
            current_chunk=8,
        )
    )
    unlocated = await service.collect(
        EvidenceRequest(
            consumer="annotation_agent",
            objective="identity",
            mode="read",
            read_chunk_id=4,
            current_chunk=8,
        )
    )

    assert current.generation_meta["read_status"] == "blocked_by_policy"
    assert future.generation_meta["read_status"] == "blocked_by_policy"
    assert mismatched_objective.generation_meta["read_status"] == "blocked_by_policy"
    assert unlocated.generation_meta["read_status"] == "blocked_by_policy"
    assert fetch.call_count == 1


@pytest.mark.asyncio
async def test_semantic_mode_is_the_only_mode_that_requires_level3_readiness() -> None:
    """
    2026-08-03 用于验证 semantic readiness 只在实际语义请求时失败
    """
    service = NarrativeEvidenceService(
        run_id="run-1",
        session=MagicMock(),
        embedding_client=None,
        level3_enabled=True,
    )

    with pytest.raises(Level3NotReadyError, match="embedding client"):
        await service.collect(
            EvidenceRequest(
                consumer="annotation_agent",
                objective="identity",
                mode="semantic",
                query_text="顾霜是谁",
                current_chunk=8,
                top_k=5,
            )
        )
