"""API 内嵌 Worker 与独立进程共用的统一 Agent 执行入口"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from src.agents.annotation.fact_graph import FactGraph
from src.agents.model_capacity import MODEL_CAPACITY
from src.agents.stream import AgentStream
from src.api.models.events import StreamEvent
from src.config import settings
from src.config.input_config import load_task_config
from src.storage.models import Chapter
from src.storage.repositories import DatabaseAnnotationQueryService, ParagraphRepository
from src.storage.repositories.formal_chapter import FormalChapterRepository
from src.storage.repositories.pipeline_work import WorkReceipt
from src.workflows.chapter_pool import AgentStatus


class PipelineAgentExecutor:
    """只执行领取的工作，不封轮次、不恢复失败 run、不改变消费者可见指针"""

    def __init__(
        self, session_factory: Callable[[], Session], *, owner: str, novel_id: str,
        novel_title: str | None = None,
        emitter: Callable[[StreamEvent], Awaitable[None]] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.owner = owner
        self.novel_id = novel_id
        self.novel_title = novel_title
        self.emitter = emitter
        self.formal = FormalChapterRepository(session_factory)

    def record_embedding_usage(self, run_id: str, *args: Any, **kwargs: Any) -> None:
        from src.agents.usage import build_token_usage_callback

        with self.session_factory() as session:
            build_token_usage_callback(session=session, run_id=run_id)(*args, **kwargs)
            session.commit()

    async def execute(self, receipt: WorkReceipt) -> AgentStatus:
        """agent 暴露给工作队列的启动接口；结束后以返回值向队列回传状态

        失败分类是 agent 层知识：瞬态（可重试的模型错误或标注错误）回传 retry 交
        队列按预算退避重试，其余（含不可变工作冲突）回传 failed；CancelledError
        原样上抛交队列的取消语义。
        """
        try:
            await self._execute_chapter(receipt)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            from src.agents.annotation.errors import AnnotationRetryableError
            from src.agents.stream import _is_transient_model_error
            from src.storage.repositories.pipeline_work import ImmutableWorkConflict

            logger.error("章节工作失败 work_id={} attempt_epoch={} error={!r}",
                         receipt.work_id, receipt.attempt_epoch, exc)
            transient = (
                not isinstance(exc, ImmutableWorkConflict)
                or isinstance(exc, AnnotationRetryableError)
                or _is_transient_model_error(exc)
            )
            return "retry" if transient else "failed"
        return "submitted"

    async def _execute_chapter(self, receipt: WorkReceipt) -> None:
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
        paragraph_info = build_chapter_paragraph_info(paragraphs)
        # 每章新建事实图：图状态不跨章节、跨尝试共享（重试重新派发后走全新图）
        graph_state = FactGraph(run_scope=receipt.run_id, chapter_id=chapter_id)
        # 2026-10-02 模型池分发：章任务由容量感知选举派发；长章的子代理按容量位
        # 拉起（1 并发下顺序过、多并发下同时起飞），不超线走单 agent 路径；
        # 两条路径返回同构的 AgentRunResult，提交事务只有一处
        if len(chapter_text) > options.sub_chunk_max_chars:
            from src.workflows.annotate_helpers.block_codeact import run_chapter_subagents

            result = await run_chapter_subagents(
                run_id=receipt.run_id, chapter_id=chapter_id, chapter_text=chapter_text,
                paragraph_info=paragraph_info, llm=model, sql_session_factory=self.session_factory,
                query_service_factory=query_factory, graph_state=graph_state, stream=stream,
                novel_id=self.novel_id, capacity=capacity,
                work_id=receipt.work_id, model_id=model_config.model,
            )
        else:
            # 派发选举已预留容量位：启动即兑现
            if not MODEL_CAPACITY.consume(receipt.work_id, model_config.model):
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
