"""章内并行两段式：Phase A 并行读者 + Phase B 单写者（含 ask_reader 反问通道）

设计文档《章内并行设计-子代理只读顾问与主代理单写者》§8/§17：
- 仅超长章（切为 ≥2 子块）走两段式；单块章维持现行单代理直读直写；
- 读者并发度 = 子块数（2026-09-11 用户裁决"切几块就开几并发"），
  任一读者失败取消其余在飞读者，整章失败（全有或全无）；
- 消息池按 (block_index, message_id) 排序消费，与读者完成顺序无关；
- 写者可经 ask_reader 追问对应块读者（轮数上限进设置，0 不限），
  读者带着 Phase A 的完整原文上下文续跑补查。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from src.agents.annotation.candidates import extract_dialogue_candidates
from src.agents.annotation.errors import AnnotationInputError
from src.agents.annotation.messages import ReaderMessagePool
from src.agents.annotation.reader import ReaderBlockContext, ReaderRunOutcome, run_reader_agent
from src.agents.annotation.runner import run_annotation_agent
from src.agents.annotation.schema import AgentRunResult, ChunkParagraphInfo
from src.agents.annotation.tools import AskReaderDispatcher

_READER_MAX_SESSION_ATTEMPTS = 3  # 2026-09-11 §8.5：首次 + 会话级重跑 ≤ 2 次


def build_candidate_number_map(
    *,
    chapter_chunk_id: int,
    chapter_text: str,
    sub_chunks: list[tuple[int, str, int]],
) -> list[dict[int, int | None]]:
    """2026-09-11 用于把各块局部候选序号映射到写者全章候选表序号

    块边界取段落边界，候选不会跨块；切分点落在引号内部时块内会出现
    unclosed_quote 截断候选，其绝对区间与章级候选不一致，映射为 None，
    由写者按消息里的候选原文自行对照全章候选表。
    """
    chapter_candidates = extract_dialogue_candidates(chapter_chunk_id, chapter_text)
    chapter_index_by_span = {
        (candidate.start, candidate.end): index
        for index, candidate in enumerate(chapter_candidates, start=1)
    }
    maps: list[dict[int, int | None]] = []
    for _sub_chunk_id, sub_chunk_text, sub_chunk_offset in sub_chunks:
        block_candidates = extract_dialogue_candidates(chapter_chunk_id, sub_chunk_text)
        mapping: dict[int, int | None] = {}
        for local_index, candidate in enumerate(block_candidates, start=1):
            chapter_index = chapter_index_by_span.get(
                (candidate.start + sub_chunk_offset, candidate.end + sub_chunk_offset)
            )
            mapping[local_index] = chapter_index
        maps.append(mapping)
    return maps


async def _run_reader_block_with_retry(
    *,
    context: ReaderBlockContext,
    pool: ReaderMessagePool,
    run_id: str,
    chapter_id: int,
    llm: Any,
    graph_state: Any | None,
    query_service_factory: Any,
    session_factory: Any,
    stream: Any | None,
    chapter_label: str | None,
    novel_id: str,
) -> ReaderRunOutcome:
    """2026-09-11 §8.5 用于带会话级重跑的单块读者执行（重跑前清空该块旧消息）"""
    last_exc: Exception | None = None
    for attempt in range(1, _READER_MAX_SESSION_ATTEMPTS + 1):
        try:
            return await run_reader_agent(
                run_id=run_id,
                chapter_id=chapter_id,
                context=context,
                pool=pool,
                query_service_factory=query_service_factory,
                session_factory=session_factory,
                llm=llm,
                graph_state=graph_state,
                stream=stream,
                chapter_label=chapter_label,
                novel_id=novel_id,
                attempt_number=attempt,
            )
        except Exception as exc:
            last_exc = exc
            pool.discard_block(context.block_index)
            logger.warning(
                "reader block failed, retrying run_id={} chapter_id={} block={} attempt={}/{} error={!r}",
                run_id,
                chapter_id,
                context.block_index + 1,
                attempt,
                _READER_MAX_SESSION_ATTEMPTS,
                exc,
            )
    assert last_exc is not None
    raise last_exc


class WriterAskReaderDispatcher:
    """2026-09-11 §17 用户裁决（追问轮数进配置）用于实现写者 ask_reader 后端

    追问把对应块读者带着 Phase A 完整消息链重新唤起（新 invocation 审计行），
    新观察经 send_message 入池并随回执同步返回写者；轮数上限取
    settings.models.annotation.writer_max_ask_rounds（0 不限）。
    """

    def __init__(
        self,
        *,
        pool: ReaderMessagePool,
        contexts: list[ReaderBlockContext],
        outcomes: list[ReaderRunOutcome],
        run_id: str,
        chapter_id: int,
        llm: Any,
        graph_state: Any | None,
        query_service_factory: Any,
        session_factory: Any,
        stream: Any | None,
        chapter_label: str | None,
        novel_id: str,
        max_ask_rounds: int,
    ) -> None:
        self._pool = pool
        self._contexts = contexts
        self._outcomes = outcomes
        self._run_id = run_id
        self._chapter_id = chapter_id
        self._llm = llm
        self._graph_state = graph_state
        self._query_service_factory = query_service_factory
        self._session_factory = session_factory
        self._stream = stream
        self._chapter_label = chapter_label
        self._novel_id = novel_id
        self._max_ask_rounds = max_ask_rounds
        self.rounds_used = 0

    async def ask(self, block: int, question: str) -> str:
        if not 1 <= block <= len(self._contexts):
            raise AnnotationInputError(
                f"ask_reader.block 超出范围: {block}，合法值 1..{len(self._contexts)}"
            )
        if self._max_ask_rounds > 0 and self.rounds_used >= self._max_ask_rounds:
            raise AnnotationInputError(
                f"追问轮数已达上限 {self._max_ask_rounds}（设置 writer_max_ask_rounds）；"
                "请基于现有消息与 search_text 取证继续写入"
            )
        self.rounds_used += 1
        context = self._contexts[block - 1]
        prior_outcome = self._outcomes[context.block_index]
        # 追问续跑只能取该 id 之后的新消息：池按块序排序，按数量切片会错位取到旧消息
        max_id_before = self._pool.max_message_id()
        continuation = await run_reader_agent(
            run_id=self._run_id,
            chapter_id=self._chapter_id,
            context=context,
            pool=self._pool,
            query_service_factory=self._query_service_factory,
            session_factory=self._session_factory,
            llm=self._llm,
            graph_state=self._graph_state,
            stream=self._stream,
            chapter_label=self._chapter_label,
            novel_id=self._novel_id,
            prior_messages=prior_outcome.final_messages,
            writer_question=question,
        )
        self._outcomes[context.block_index] = continuation
        new_messages = self._pool.messages_since(max_id_before)
        return json.dumps(
            {
                "accepted": True,
                "block": block,
                "round": self.rounds_used,
                "new_messages": [
                    {
                        "message_id": message.message_id,
                        "kind": message.kind,
                        "summary": message.summary,
                    }
                    for message in new_messages
                ],
            },
            ensure_ascii=False,
        )


async def run_chapter_two_phase(
    *,
    run_id: str,
    chapter_id: int,
    chapter_chunk_id: int,
    chapter_text: str,
    chapter_paragraph_rows: list[Any],
    sub_chunks: list[tuple[int, str, int]],
    llm: Any,
    sql_session_factory: Any,
    query_service_factory: Any,
    graph_state: Any | None,
    stream: Any | None,
    novel_id: str,
    novel_title: str | None,
    chapter_label: str | None,
) -> AgentRunResult:
    """2026-09-11 章内并行（§8）用于以两段式执行超长章标注并返回章级单写者结果

    Phase A：每块一个读者，全部并行（asyncio.gather），任一失败取消其余并上抛；
    Phase B：单写者消费按块序排列的消息池，产出章级 AgentRunResult（含图域
    操作日志 drain），调用方直接进完成事务、无需子块合并。
    """
    from src.agents.annotation.prompts import build_system_prompt, build_writer_chapter_message

    chapter_candidates = extract_dialogue_candidates(chapter_chunk_id, chapter_text)
    candidate_maps = build_candidate_number_map(
        chapter_chunk_id=chapter_chunk_id,
        chapter_text=chapter_text,
        sub_chunks=sub_chunks,
    )
    contexts: list[ReaderBlockContext] = []
    for sub_chunk_index, (sub_chunk_id, sub_chunk_text, sub_chunk_offset) in enumerate(sub_chunks):
        contexts.append(
            ReaderBlockContext(
                block_index=sub_chunk_index,
                block_count=len(sub_chunks),
                block_chunk_id=sub_chunk_id,
                block_text=sub_chunk_text,
                paragraph_info=build_block_paragraph_info(
                    chapter_paragraph_rows,
                    sub_chunk_offset=sub_chunk_offset,
                    sub_chunk_text=sub_chunk_text,
                ),
                candidate_number_map=candidate_maps[sub_chunk_index],
            )
        )
    pool = ReaderMessagePool()

    # ---- Phase A：并行读者（切几块开几并发；任一失败取消其余，整章失败）----
    reader_tasks = [
        asyncio.ensure_future(
            _run_reader_block_with_retry(
                context=context,
                pool=pool,
                run_id=run_id,
                chapter_id=chapter_id,
                llm=llm,
                graph_state=graph_state,
                query_service_factory=query_service_factory,
                session_factory=sql_session_factory,
                stream=stream,
                chapter_label=chapter_label,
                novel_id=novel_id,
            )
        )
        for context in contexts
    ]
    try:
        outcomes = await asyncio.gather(*reader_tasks)
    except BaseException:
        for task in reader_tasks:
            task.cancel()
        await asyncio.gather(*reader_tasks, return_exceptions=True)
        raise

    # ---- Phase B：单写者（消息池准入 + ask_reader 反问通道）----
    from src.config import settings

    dispatcher = WriterAskReaderDispatcher(
        pool=pool,
        contexts=contexts,
        outcomes=list(outcomes),
        run_id=run_id,
        chapter_id=chapter_id,
        llm=llm,
        graph_state=graph_state,
        query_service_factory=query_service_factory,
        session_factory=sql_session_factory,
        stream=stream,
        chapter_label=chapter_label,
        novel_id=novel_id,
        max_ask_rounds=settings.models.annotation.writer_max_ask_rounds,
    )
    writer_paragraph_info = build_block_paragraph_info(
        chapter_paragraph_rows,
        sub_chunk_offset=0,
        sub_chunk_text=chapter_text,
    )
    writer_result = await run_annotation_agent(
        run_id=run_id,
        chapter_id=chapter_id,
        current_chunks=[(chapter_chunk_id, chapter_text)],
        query_service_factory=query_service_factory,
        session_factory=sql_session_factory,
        novel_title=novel_title,
        novel_id=novel_id,
        llm=llm,
        stream=stream,
        graph_state=graph_state,
        chapter_label=chapter_label,
        sub_chunk_index=0,
        paragraph_info=writer_paragraph_info,
        reader_message_pool=pool,
        ask_reader_dispatcher=dispatcher,
        initial_messages_override=[
            _system_message(build_system_prompt()),
            _human_message(
                build_writer_chapter_message(
                    reader_messages_view=pool.writer_view(),
                    candidates=chapter_candidates,
                )
            ),
        ],
    )
    # 读者是本设计里唯一见过正文的一方：其文本授权足迹并入章级审计
    reader_paragraph_ids: set[int] = set()
    reader_chapter_ids: set[int] = set()
    for outcome in outcomes:
        reader_paragraph_ids |= outcome.authorized_text_paragraph_ids
        reader_chapter_ids |= outcome.authorized_chapter_ids
    merged_audit = writer_result.audit.model_copy(
        update={
            "authorized_text_paragraph_ids": sorted(
                set(writer_result.audit.authorized_text_paragraph_ids) | reader_paragraph_ids
            ),
            "authorized_chapter_ids": sorted(
                set(writer_result.audit.authorized_chapter_ids) | reader_chapter_ids
            ),
        }
    )
    return writer_result.model_copy(update={"audit": merged_audit})


def build_block_paragraph_info(
    chapter_paragraph_rows: list[Any],
    *,
    sub_chunk_offset: int,
    sub_chunk_text: str,
) -> ChunkParagraphInfo:
    """2026-09-11 用于复用 annotate 的段落坐标映射构建（此处仅避免环依赖的薄封装）"""
    from src.workflows.annotate import _build_sub_chunk_paragraph_info

    return _build_sub_chunk_paragraph_info(
        chapter_paragraph_rows,
        sub_chunk_offset=sub_chunk_offset,
        sub_chunk_text=sub_chunk_text,
    )


def _system_message(content: str) -> Any:
    from langchain_core.messages import SystemMessage

    return SystemMessage(content=content)


def _human_message(content: str) -> Any:
    from langchain_core.messages import HumanMessage

    return HumanMessage(content=content)


__all__ = [
    "AskReaderDispatcher",
    "WriterAskReaderDispatcher",
    "build_candidate_number_map",
    "run_chapter_two_phase",
]
