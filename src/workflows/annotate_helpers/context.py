"""
标注辅助函数模块 - 证据服务与全局上下文
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from src.api.models.events import StreamEvent
from src.config import settings
from src.rag import NarrativeEvidenceService


def _init_evidence_service(
    conn,
    novel_id: str,
    use_rag: bool,
    run_id: str | None = None,
    emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
) -> NarrativeEvidenceService | None:
    """初始化 evidence service（Level1/2/3，Level3 粒度固定为自然段）"""
    if not use_rag or not settings.rag.enabled:
        return None

    from src.storage.repositories import GraphRepository

    logger.info("initializing narrative evidence service")

    graph_repo = GraphRepository(conn)

    embedding_client = None
    if settings.rag.embedding_enabled and settings.rag.level3_enabled:
        try:
            from src.models.local.embedding import EmbeddingClient

            embedding_client = EmbeddingClient(novel_id=novel_id)
            logger.info("Level 3 paragraph retrieval enabled and required")
        except ValueError as e:
            logger.error(
                "EmbeddingClient initialization failed; Level 3 is required and annotation will fail readiness "
                f"checks: {e}"
            )

    evidence_service = NarrativeEvidenceService(
        graph_repo=graph_repo,
        novel_id=novel_id,
        run_id=run_id,
        lookback_chunks=settings.rag.lookback_chunks,
        session=conn,
        embedding_client=embedding_client,
        level1_enabled=settings.rag.level1_enabled,
        level2_enabled=settings.rag.level2_enabled,
        level3_enabled=settings.rag.level3_enabled,
        similarity_threshold=settings.rag.similarity_threshold,
        level3_top_k=settings.rag.level3_top_k,
        progress_emitter=emitter,
    )

    return evidence_service


class _GlobalContextClientAdapter:
    """
    把 langchain ChatOpenAI 适配成 src.context.extract_global_context 期望的
    client._client.chat.completions.create 形态
    """

    def __init__(self, llm: Any) -> None:
        self._client = llm.async_client
        self._config = _ModelConfigProxy(llm.model_name)


class _ModelConfigProxy:
    def __init__(self, model_name: str) -> None:
        self.model = model_name


async def _extract_and_save_global_context(
    conn,
    all_chunks: list,
    novel_id: str,
    novel_title: str | None,
    use_context_enhancement: bool,
    resume: bool,
    llm: Any,
    run_id: str | None = None,
) -> str | None:
    """提取并保存全局上下文"""
    if not use_context_enhancement or resume:
        return None

    from src.context import extract_global_context, format_global_context_for_prompt

    first_chunks = [text for _, text in all_chunks[:3]]
    if not first_chunks:
        return None

    logger.info("extracting global context from first chunks")
    global_context = await extract_global_context(first_chunks, client=_GlobalContextClientAdapter(llm))

    if run_id:
        from src.storage.repositories import StatsRepository

        stats_repo = StatsRepository(conn)
        stats_repo.insert_global_context(
            run_id,
            novel_id,
            ",".join(global_context.get("core_characters", [])),
            global_context.get("world_setting", ""),
            novel_title,
        )
    else:
        from src.context import save_global_context

        save_global_context(
            conn,
            novel_id,
            global_context.get("core_characters", []),
            global_context.get("world_setting", ""),
            novel_title,
        )

    global_context_str = format_global_context_for_prompt(global_context)
    logger.info(f"global context extracted: {len(global_context.get('core_characters', []))} core characters")

    return global_context_str
