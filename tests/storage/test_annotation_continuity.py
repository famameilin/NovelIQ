"""章节 Agent 连续性查询仓储测试"""

from __future__ import annotations

import pytest

from src.agents.annotation.schema import (
    CaseSearchResult,
    PendingCase,
)
from src.config import settings
from src.storage.repositories.annotation.continuity import (
    CasePoolRepository,
    DatabaseAnnotationQueryService,
)
from tests.support.chapter_annotation_helpers import (
    create_run_with_chunks,
    persist_chapter_annotation,
)


def test_case_search_returns_id_for_keys_and_description_pull(db_session) -> None:
    """2026-08-06 用于验证案例按 keys 与 description 查得真实 ID 后可回读"""
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜身份成谜"],
        title="案例联合检索",
    )
    annotation_id = persist_chapter_annotation(
        db_session,
        run_id=run_id,
        chapter_id=1,
    )
    row = CasePoolRepository(db_session).create_case(
        run_id=run_id,
        annotation_id=annotation_id,
        pending_case=PendingCase(
            type="dialogue_speaker",
            keys=["顾霜"],
            description="真实身份悬而未决",
            chunk_id=0,
            target_key="target-case-1",
            target_ref={
                "kind": "dialogue",
                "dialogue_id": "candidate-1",
                "chunk_id": 0,
                "start": 0,
                "end": 2,
                "text": "顾霜",
            },
        ),
    )
    db_session.commit()
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=1,
        current_first_chunk_id=0,
        current_last_chunk_id=0,
    )

    key_matches = [
        item
        for item in service.search_pool("顾霜", hidden_case_ids=set()).results
        if isinstance(item, CaseSearchResult)
    ]
    description_matches = [
        item
        for item in service.search_pool("身份悬而未决", hidden_case_ids=set()).results
        if isinstance(item, CaseSearchResult)
    ]

    assert [item.id for item in key_matches] == [row.id]
    assert [item.id for item in description_matches] == [row.id]
    details = service.fetch_active_case_details(row.id)
    assert details is not None
    assert details.id == row.id
    assert details.type == "dialogue_speaker"


@pytest.mark.asyncio
async def test_text_search_returns_only_matching_later_chunks(db_session, monkeypatch) -> None:
    """2026-08-06 用于验证后文搜索只返回当前位置之后的匹配章节与 chunk"""
    monkeypatch.setattr(settings.models.paragraph_embedding, "semantic_enabled", False)
    _novel_id, run_id = create_run_with_chunks(
        db_session,
        texts=["顾霜在当前章现身", "第二章没有目标内容", "第三章顾霜身份揭晓"],
        chapter_ids=[1, 2, 3],
        title="后文动态检索",
    )
    service = DatabaseAnnotationQueryService(
        db_session,
        run_id=run_id,
        current_chapter_id=1,
        current_first_chunk_id=0,
        current_last_chunk_id=0,
    )

    results = await service.search_text("顾霜", range_name="future")

    assert [(item.chapter_id, item.chunk_id) for item in results] == [(3, 2)]
    assert "顾霜" in results[0].excerpt
    assert service.read_text(2) == "第三章顾霜身份揭晓"
    with pytest.raises(ValueError, match="原文 chunk 不存在或跨 run"):
        service.read_text(999)
