"""API 内嵌 Worker 与独立进程共用的统一 Agent 执行入口"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

from sqlalchemy.orm import Session

from src.agents.annotation.fact_graph import FactGraph
from src.agents.model_capacity import MODEL_CAPACITY
from src.agents.provider_runtime import ProviderRequestScope, provider_request_scope
from src.agents.stream import AgentStream
from src.agents.work_context import AgentWorkContext, agent_work_context
from src.api.models.events import StreamEvent
from src.config import settings
from src.config.input_config import load_task_config
from src.storage.models import Chapter
from src.storage.repositories import DatabaseAnnotationQueryService, ParagraphRepository
from src.storage.repositories.formal_chapter import FormalChapterRepository
from src.storage.repositories.pipeline_work import WorkReceipt
from src.storage.repositories.provider_permits import ProviderPermitRepository


class PipelineAgentExecutor:
    """只执行领取的工作，不封轮次、不恢复失败 run、不改变消费者可见指针"""

    def __init__(
        self, session_factory: Callable[[], Session], *, owner: str, novel_id: str,
        novel_title: str | None = None, is_cancelled: Callable[[], bool] | None = None,
        emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.owner = owner
        self.novel_id = novel_id
        self.novel_title = novel_title
        self.is_cancelled = is_cancelled
        self.emitter = emitter
        self.permits = ProviderPermitRepository(session_factory)
        self.formal = FormalChapterRepository(session_factory)

    def record_embedding_usage(self, run_id: str, *args: Any, **kwargs: Any) -> None:
        from src.agents.usage import build_token_usage_callback

        with self.session_factory() as session:
            build_token_usage_callback(session=session, run_id=run_id)(*args, **kwargs)
            session.commit()

    async def execute(self, receipt: WorkReceipt) -> None:
        from src.agents.annotation import run_annotation_agent
        from src.agents.annotation.paragraphs import build_chapter_paragraph_info
        from src.agents.llm import build_chat_model
        from src.models.local.embedding import EmbeddingClient

        if receipt.work_kind != "formal_current":
            raise ValueError("标注执行入口只接受章节任务")
        chapter_id = int(receipt.payload["chapter_id"])
        with self.session_factory() as session:
            chapter = session.get(Chapter, (chapter_id, receipt.run_id))
            if chapter is None or chapter.text is None:
                raise ValueError(f"工作来源章节不存在: chapter_id={chapter_id}")
            chapter_text = chapter.text
            paragraphs = ParagraphRepository(session).fetch_chapter_paragraph_rows(receipt.run_id, chapter_id)
        if not paragraphs:
            raise ValueError("工作来源章节没有原文段落")
        model_config = load_task_config("annotation", model_id=receipt.payload["model_id"])
        model = build_chat_model("annotation", config=model_config)
        # 2026-10-02 并发语义归位：容量位跟 agent 生命周期——短章 agent 整生命周期占
        # 一个位；长章由 run_chapter_subagents 按位拉起子代理（拿到位才启动）
        assert model_config.model is not None  # validate() 已保证模型标识非空
        capacity = MODEL_CAPACITY.slots(model_config.model, model_config.max_in_flight)
        embedding = EmbeddingClient(novel_id=self.novel_id,
                                    token_usage_callback=partial(self.record_embedding_usage, receipt.run_id))
        query_factory = partial(
            DatabaseAnnotationQueryService, run_id=receipt.run_id, current_chapter_id=chapter_id,
            current_first_paragraph_id=min(row.paragraph_id for row in paragraphs),
            current_last_paragraph_id=max(row.paragraph_id for row in paragraphs), embedding_client=embedding,
        )
        stream = AgentStream(self.emitter, chapter_id=chapter_id,
                             sub_stage="chapter_agent") if self.emitter else None
        options = settings.models.annotation
        scope = ProviderRequestScope(
            repository=self.permits, owner=self.owner, work_id=receipt.work_id,
            hard_max_in_flight=model_config.max_in_flight, is_cancelled=self.is_cancelled,
            model_pool_managed=True,
        )
        paragraph_info = build_chapter_paragraph_info(paragraphs)
        # 每章新建事实图：图状态不跨章节、跨尝试共享（重试由队列重新领取后走全新图）
        graph_state = FactGraph(run_scope=receipt.run_id, chapter_id=chapter_id)
        with provider_request_scope(scope), agent_work_context(AgentWorkContext(
            receipt.work_id, receipt.attempt_epoch, receipt.cutoff_hash, model_config.provider_id,
        )):
            # 2026-10-02 模型池分发：章任务由容量感知选举领取；长章的子代理按容量位
            # 拉起（1 并发下顺序过、多并发下同时起飞），不超线走单 agent 路径；
            # 两条路径返回同构的 AgentRunResult，提交事务只有一处
            if len(chapter_text) > options.sub_chunk_max_chars:
                from src.workflows.annotate_helpers.block_codeact import run_chapter_subagents

                result = await run_chapter_subagents(
                    run_id=receipt.run_id, chapter_id=chapter_id, chapter_text=chapter_text,
                    paragraph_info=paragraph_info, llm=model, sql_session_factory=self.session_factory,
                    query_service_factory=query_factory, graph_state=graph_state, stream=stream,
                    novel_id=self.novel_id, capacity=capacity,
                )
            else:
                await capacity.acquire()
                try:
                    result = await run_annotation_agent(
                        run_id=receipt.run_id, chapter_id=chapter_id, chapter_text=chapter_text,
                        novel_title=self.novel_title, novel_id=self.novel_id, llm=model,
                        session_factory=self.session_factory, query_service_factory=query_factory,
                        stream=stream, graph_state=graph_state, chapter_label=receipt.payload["chapter_label"],
                        paragraph_info=paragraph_info,
                    )
                finally:
                    await capacity.release()
        await asyncio.to_thread(self.formal.commit, receipt, result)
