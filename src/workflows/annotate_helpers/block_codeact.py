"""章内并行 CodeAct 工作流：N 个块代理（程序面）+ 1 个章节代理（合并面）

设计（章内并行 CodeAct 方案 §2/§4/§5/§8）：
- 切多少块就开多少并发：每块一个块代理会话，全部同时起飞（asyncio.ensure_future
  + gather），没有并发上限、没有信号量、没有共享请求池；每个会话的轮次上限仍然是
  各自的 max_iterations，谁先用完谁先收束；
- 块完成顺序不构成任何语义顺序：块代理只产出内存里的局部标注（BlockAnnotation），
  会话之间零共享状态、零正式写入，gather 的结果按块序装配；
- 任一失败取消其余在飞块，整章失败（全有或全无）——与两段式读者面同一条既有失败
  路径；块内不做会话级重跑，块代理的修复只发生在它自己的轮次里（无升级分支）；
- 章会话只补全章层面决策：绑定、跨块事件归并、参与者冲突裁决、指标与待决项；
  块内提及/事件/对话按句柄引用，编译成正式调用后走生产单条事务边界就地生效；
- 块代理是唯一见过正文与案例池的一方，其授权足迹（正文/章/事件/案例）在章会话
  开始前并入章账本；实体名与案例理由的准入复用两段式那条既有硬门槛。

生产默认路径不变：本章节只被独立实验入口调用，annotate 工作流一行未改。
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from src.agents.annotation.block_program import (
    BlockContext,
    BlockRunOutcome,
    render_block_index,
    run_block_agent,
)
from src.agents.annotation.candidates import extract_dialogue_candidates
from src.agents.annotation.chapter_merge import (
    ChapterMergeRuntime,
    build_block_reports,
    transfer_authorizations,
)
from src.agents.annotation.errors import AnnotationInputError
from src.agents.annotation.local_ir import BlockAnnotation
from src.agents.annotation.runner import run_annotation_agent
from src.agents.annotation.schema import AgentRunResult
from src.workflows.annotate_helpers.two_phase import (
    build_block_paragraph_info,
    build_candidate_number_map,
)


def build_block_boundaries(
    chapter_paragraph_rows: list[Any],
    *,
    sub_chunk_offset: int,
    sub_chunk_text: str,
) -> tuple[tuple[int, str] | None, tuple[int, str] | None]:
    """用于取本块前后各一个完整段落作为只读边界上下文（判跨块延续用）

    边界段落只进上下文、不进证据面：块代理的 evidence 锚点只能落在本块段落上
    （构造器按本块段落表校验）。首块无前邻、末块无后邻。
    """
    ordered = sorted(chapter_paragraph_rows, key=lambda row: int(row.local_start_char))
    block_start = sub_chunk_offset
    block_end = sub_chunk_offset + len(sub_chunk_text)
    inside = [
        index
        for index, row in enumerate(ordered)
        if int(row.local_start_char) >= block_start and int(row.local_end_char) <= block_end
    ]
    if not inside:
        return (None, None)
    first, last = inside[0], inside[-1]
    before = ordered[first - 1] if first > 0 else None
    after = ordered[last + 1] if last + 1 < len(ordered) else None
    return (
        (int(before.paragraph_id), str(before.text)) if before is not None else None,
        (int(after.paragraph_id), str(after.text)) if after is not None else None,
    )


def build_block_contexts(
    *,
    chapter_paragraph_rows: list[Any],
    sub_chunks: list[tuple[int, str, int]],
    candidate_maps: list[dict[int, int | None]],
) -> list[BlockContext]:
    """用于构建各块代理会话的输入上下文（切块身份、段落坐标、候选映射、边界段落）"""
    contexts: list[BlockContext] = []
    for sub_chunk_index, (sub_chunk_id, sub_chunk_text, sub_chunk_offset) in enumerate(sub_chunks):
        boundary_before, boundary_after = build_block_boundaries(
            chapter_paragraph_rows,
            sub_chunk_offset=sub_chunk_offset,
            sub_chunk_text=sub_chunk_text,
        )
        contexts.append(
            BlockContext(
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
                boundary_before=boundary_before,
                boundary_after=boundary_after,
            )
        )
    return contexts


def render_pending_view(blocks: list[BlockAnnotation]) -> str:
    """用于把各块待决项渲染成章会话的 <PendingItems> 区块（空即整块不出现）"""
    lines: list[str] = []
    for block in blocks:
        for item in block.pending:
            detail = f"- {block.handle(item.key)} [{item.kind}] {item.detail}"
            extras: list[str] = []
            if item.handles:
                extras.append("相关句柄：" + "、".join(item.handles))
            if item.case_id is not None:
                extras.append(f"案例 id：{item.case_id}")
            if extras:
                detail += "（" + "；".join(extras) + "）"
            lines.append(detail)
    return "\n".join(lines)


async def run_chapter_block_codeact(
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
    """用于以"N 块代理全并行 + 1 章节代理合并"执行超长章标注并返回章级结果

    返回值与两段式同构（AgentRunResult，含图域操作日志 drain），调用方直接进完成
    事务。块代理的正文/章/事件/案例授权足迹已并入返回审计，无需调用方补并。

    并发=块数：长章块数多时同时持有等量的只读数据库连接（连接池上限见
    DB_POOL_SIZE/DB_MAX_OVERFLOW），不做排队——这是设计口径，不是缺省。
    """
    from src.config import settings

    if not settings.models.annotation.codeact_enabled:
        raise AnnotationInputError(
            "块面章内并行是 CodeAct 路径，需要 codeact_enabled=True（当前设置已关闭）"
        )

    candidate_maps = build_candidate_number_map(
        chapter_chunk_id=chapter_chunk_id,
        chapter_text=chapter_text,
        sub_chunks=sub_chunks,
    )
    contexts = build_block_contexts(
        chapter_paragraph_rows=chapter_paragraph_rows,
        sub_chunks=sub_chunks,
        candidate_maps=candidate_maps,
    )
    logger.info(
        "block codeact dispatch run_id={} chapter_id={} blocks={}",
        run_id,
        chapter_id,
        len(contexts),
    )

    # ---- 块代理：切几块开几并发（任一失败取消其余，整章失败）----
    block_tasks = [
        asyncio.ensure_future(
            run_block_agent(
                run_id=run_id,
                chapter_id=chapter_id,
                context=context,
                query_service_factory=query_service_factory,
                session_factory=sql_session_factory,
                llm=llm,
                graph_state=graph_state,
                stream=stream,
                chapter_label=chapter_label,
                novel_id=novel_id,
            )
        )
        for context in contexts
    ]
    try:
        outcomes: list[BlockRunOutcome] = list(await asyncio.gather(*block_tasks))
    except BaseException:
        for task in block_tasks:
            task.cancel()
        await asyncio.gather(*block_tasks, return_exceptions=True)
        raise

    # gather 结果顺序 = contexts 顺序，与完成时序无关（块完成顺序不构成语义顺序）
    blocks = [outcome.block for outcome in sorted(outcomes, key=lambda item: item.block.block_index)]
    block_reports = build_block_reports(blocks)

    # ---- 章节代理：只补全章层面决策（绑定即编译、就地执行）----
    chapter_candidates = extract_dialogue_candidates(chapter_chunk_id, chapter_text)
    chapter_paragraph_info = build_block_paragraph_info(
        chapter_paragraph_rows,
        sub_chunk_offset=0,
        sub_chunk_text=chapter_text,
    )

    def chapter_program_factory(
        tools: list[Any],
        ledger: Any,
        *,
        observer: Any = None,
        stream: Any = None,
    ) -> Any:
        """用于把合并程序面注入章会话（先并入块代理授权足迹，再建运行时）"""
        transfer_authorizations(ledger, outcomes)
        runtime = ChapterMergeRuntime(
            tools,
            ledger,
            blocks,
            candidate_number_maps=candidate_maps,
            observer=observer,
            stream=stream,
        )
        return runtime.build_tool()

    from langchain_core.messages import HumanMessage, SystemMessage

    from src.agents.annotation.prompts import build_chapter_merge_message, build_system_prompt

    return await run_annotation_agent(
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
        paragraph_info=chapter_paragraph_info,
        # 块代理是本设计里唯一见过正文的一方：按既有报告形状喂进章级取证准入
        reader_reports=block_reports,
        initial_messages_override=[
            SystemMessage(content=build_system_prompt(program_mode=True)),
            HumanMessage(
                content=build_chapter_merge_message(
                    block_index_view=render_block_index(blocks),
                    pending_view=render_pending_view(blocks),
                    candidates=chapter_candidates,
                    block_total=len(blocks),
                )
            ),
        ],
        program_mode=True,
        program_tool_factory=chapter_program_factory,
    )


__all__ = [
    "build_block_boundaries",
    "build_block_contexts",
    "render_pending_view",
    "run_chapter_block_codeact",
]
