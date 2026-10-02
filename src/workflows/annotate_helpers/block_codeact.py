"""章内多代理并发：N 个 subagent（超长章 3 条 / 短章 1 条）→ 写入生效 → 接续层 → 收尾

设计（《章内多代理重设计-三代理并发版》§0/§5/§9）：

- **章的划分只有 1 个和 3 个两种形态**：超过 `sub_chunk_max_chars`（设置项，默认 5000）
  的章开三条职责 subagent（实体与关系 / 事件与参与者 / 对话与章级证据），各持**整章正文**
  （不切分正文）；不超线的章走单 agent 路径（runner.run_annotation_agent）。
  两种形态的模型可见面完全相同（只有 execute_code 与 finish，八类构造器全在
  execute_code 的目录里）；
- **写入生效**：所有 subagent 共享同一个章级账本与同一张事实图，构造器当场经生产单条
  事务边界落库（内层调用按章级锁串行；模型生成期间不占锁、不占数据库连接）；
- 全部 subagent 收束后由**跨 agent 接续层**（subagent_connect）处理跨 agent 残余
  （展示名分歧挂案例）；节点写入不经过它；
- 章级收尾由代码完成（0 个模型回合）：指标与段落标签一次落库（缺指标即中性兜底）→
  finish 冻结 → 组装章级结果。收尾走同一个 `finish` 实现，因此本章产出的形状、审计与
  完成事务输入与单 agent 路径逐字一致；
- 任一 subagent 失败取消其余在飞 subagent，整章失败（全有或全无）——与既有失败路径同一条。

2026-10-02 对齐 0.2.0：paragraph_info 由派发方构建直传（复用 annotation.paragraphs 的
单一实现）；FactGraph 每章新建（章生命周期方法移除）；结果对齐 0.2.0 schema
（去 resolved_cases/authorized_chapter_ids，补 cross_chapter_links/source_anchors）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from src.agents.annotation.errors import AnnotationRetryableError
from src.agents.annotation.graph import _execute_call
from src.agents.annotation.runner import validate_bound_annotation
from src.agents.annotation.schema import AgentRunAudit, AgentRunResult, ChapterParagraphInfo
from src.agents.annotation.subagent_connect import SubagentConnectionLayer
from src.agents.annotation.subagent_ir import SubagentAnnotation
from src.agents.annotation.subagent_program import SUBAGENT_ROLES, run_subagent_agent
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools

# 指标缺提交时收尾会被拒（finish 硬前提），所以章收尾链必须给出一条兜底指标；
# 兜底值一律中性且把"缺失"写进正文，禁止把它伪装成模型产出的摘要
_MISSING_METRIC_SUMMARY = "（证据 subagent 未提交本章摘要，此为收束兜底记录）"


async def run_chapter_subagents(
    *,
    run_id: str,
    chapter_id: int,
    chapter_text: str,
    paragraph_info: ChapterParagraphInfo,
    llm: Any,
    sql_session_factory: Any,
    query_service_factory: Any,
    graph_state: Any | None,
    stream: Any | None,
    novel_id: str,
    audit_recorder: Any | None = None,
    roles: tuple[str, ...] = SUBAGENT_ROLES,
    capacity: Any | None = None,
) -> AgentRunResult:
    """用于以"N 个 subagent 各持整章 + 构造器写入生效"执行一章标注并返回章级结果

    2026-09-19 双路径定案：本入口是多块章的 subagent 路径（单块章走 runner 的
    agent 路径），章级块身份即 chapter_id。paragraph_info 由派发方按本章段落行
    构建后直传（整章一个单元、偏移恒为 0，段落 id 即全局 paragraph_id）。

    返回值与 agent 路径同构（AgentRunResult，含图域操作日志 drain），调用方直接进
    完成事务。授权足迹与案例记录都落在共享账本上，无需调用方补并。

    并发 = 容量位跟 agent 生命周期：子代理拿到模型容量位才拉起（启动即干活），完成归还；
    容量足时三条同时起飞，不足时按完成顺序排队过（1 并发下顺序执行）。任一失败停止
    派发并取消在飞，整章失败。查询服务按单次工具调用取还连接，模型生成期间不占数据库
    连接。roles 供派发方按章长选择组合。
    """
    from src.config import settings

    if not roles:
        raise AnnotationRetryableError("多代理路径至少要有一个 subagent")

    logger.info(
        "chapter subagents dispatch run_id={} chapter_id={} roles={} chars={}",
        run_id,
        chapter_id,
        list(roles),
        len(chapter_text),
    )

    # 共享章级账本：各 subagent 的写入都落在它上面（案例编号全章唯一、检索当轮可见），
    # 内层调用按章级锁串行（账本快照/按条回滚与事实图写入都假定串行）
    query_service = query_service_factory(sql_session_factory)
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=chapter_id,
        current_chapter_text=chapter_text,
        allow_future_context=settings.models.annotation.allow_future_context,
        graph=graph_state,
        paragraph_info=paragraph_info,
        current_chapter_order=getattr(query_service, "current_chapter_order", None),
    )
    tool_map = {str(tool.name): tool for tool in build_annotation_tools(query_service, ledger)}
    write_lock = asyncio.Lock()
    subagents = [SubagentAnnotation(role=role) for role in roles]

    # ---- subagent 相位：容量位跟 agent 生命周期——拿到位才拉起（启动即干活、无
    #      空转占用），任一失败停止派发并取消在飞，整章失败（全有或全无）----
    tasks: list[asyncio.Task[Any]] = []
    failure: BaseException | None = None
    failure_event = asyncio.Event()

    def _record_failure(task: asyncio.Task[None]) -> None:
        nonlocal failure
        if failure is None and not task.cancelled():
            exc = task.exception()
            if exc is not None:
                failure = exc
                failure_event.set()

    async def _run_role(role: str, subagent: SubagentAnnotation) -> None:
        try:
            await run_subagent_agent(
                run_id=run_id,
                chapter_id=chapter_id,
                role=role,
                subagent=subagent,
                ledger=ledger,
                tool_map=tool_map,
                write_lock=write_lock,
                llm=llm,
                session_factory=sql_session_factory,
                graph_state=graph_state,
                stream=stream,
                audit_recorder=audit_recorder,
                novel_id=novel_id,
            )
        finally:
            if capacity is not None:
                await capacity.release()

    for role, subagent in zip(roles, subagents, strict=True):
        if capacity is None:
            tasks.append(asyncio.ensure_future(
                run_subagent_agent(
                    run_id=run_id, chapter_id=chapter_id, role=role, subagent=subagent,
                    ledger=ledger, tool_map=tool_map, write_lock=write_lock, llm=llm,
                    session_factory=sql_session_factory, graph_state=graph_state, stream=stream,
                    audit_recorder=audit_recorder, novel_id=novel_id,
                )
            ))
            tasks[-1].add_done_callback(_record_failure)
            continue
        acquire_fut = asyncio.ensure_future(capacity.acquire())
        failure_fut = asyncio.ensure_future(failure_event.wait())
        await asyncio.wait({acquire_fut, failure_fut}, return_when=asyncio.FIRST_COMPLETED)
        failure_fut.cancel()
        if failure_event.is_set():
            # 派发中途有人失败：未拿到的位不再等，已拿到的位归还（不带上未启动的 agent）
            if acquire_fut.done() and not acquire_fut.cancelled() and acquire_fut.exception() is None:
                await capacity.release()
            else:
                acquire_fut.cancel()
            break
        tasks.append(asyncio.ensure_future(_run_role(role, subagent)))
        tasks[-1].add_done_callback(_record_failure)

    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if graph_state is not None:
            graph_state.reset_chapter_changes()
        raise
    if failure is not None:
        if graph_state is not None:
            graph_state.reset_chapter_changes()
        assert failure is not None
        raise failure

    # ---- 章收尾相位：接续层挂案例 → 指标/标签落库 → finish → 章级结果 ----
    return await _finish_chapter(
        run_id=run_id,
        chapter_id=chapter_id,
        chapter_text=chapter_text,
        chapter_paragraph_info=paragraph_info,
        subagents=subagents,
        ledger=ledger,
        tool_map=tool_map,
        graph_state=graph_state,
        stream=stream,
    )


async def _finish_chapter(
    *,
    run_id: str,
    chapter_id: int,
    chapter_text: str,
    chapter_paragraph_info: ChapterParagraphInfo,
    subagents: list[SubagentAnnotation],
    ledger: AnnotationToolLedger,
    tool_map: dict[str, Any],
    graph_state: Any | None,
    stream: Any | None,
) -> AgentRunResult:
    """用于执行章收尾相位（0 个模型回合）：接续 → 指标/标签 → finish → 章级结果

    与单 agent 路径共用同一条账本与同一份工具表，收尾判定也走同一个 `finish`
    实现——所以"本章产出合法"这条判定只有一处，两条路径不会漂移。
    """
    from src.config import settings

    layer = SubagentConnectionLayer(ledger, tool_map, subagents, observer=None, stream=stream)
    connection = await layer.connect()
    try:
        # 2026-10-02 对齐 0.2.0：finish 收紧为"拒绝未判候选"（不补造未判内容），所以
        # 缺口闸门放行后仍存在的未判候选在这里按 not_dialogue 显式落库（可见降级）——
        # 降级动作走生产写入面、留审计记录，账本合同保持严格不分叉
        defaulted = await _default_undecided_dialogues(tool_map, ledger, stream=stream)
        await _write_chapter_metrics(tool_map, ledger, subagents, stream=stream)
        await _settle_chapter(tool_map, ledger, stream=stream)
        # 收尾声明只是"可以冻结了"：真正把本章 与本章组装出来的是这两步，单 agent
        # 路径由图的 auto_finalize 节点执行（graph._build_auto_finalize_node），本路径
        # 没有图，所以在这里按同一顺序补齐——覆盖率告警也随之落进章。
        ledger.complete_active_chapter()
        ledger.finish()
    except BaseException:
        # 收尾之前的写入已经落进共享事实图：失败时按单 agent 路径同一条口径恢复章节前
        # 快照，避免脏状态残留到后续章节
        if graph_state is not None:
            graph_state.reset_chapter_changes()
        raise
    logger.info(
        "chapter subagents merged run_id={} chapter_id={} connection={} defaulted_dialogues={}",
        run_id,
        chapter_id,
        connection.to_dict(),
        defaulted,
    )
    if ledger.annotation is None:
        raise AnnotationRetryableError("章级收尾未产出标注结果（finish 未完成组装）")
    validate_bound_annotation(
        ledger.annotation,
        chapter_id=chapter_id,
        chapter_text=chapter_text,
        paragraph_info=chapter_paragraph_info,
    )
    result = AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=ledger.annotation,
        pushed_cases=list(ledger.pushed_cases),
        cross_chapter_links=list(ledger.cross_chapter_links),
        audit=AgentRunAudit(
            allow_future_context=settings.models.annotation.allow_future_context,
            write_records=list(ledger.write_records),
            authorized_text_paragraph_ids=sorted(ledger.authorized_text_paragraph_ids),
            source_anchors=ledger.source_anchors,
        ),
    )
    if graph_state is not None:
        result = result.model_copy(update=graph_state.drain_ops())
    return result


async def _default_undecided_dialogues(
    tool_map: dict[str, Any],
    ledger: AnnotationToolLedger,
    *,
    stream: Any | None,
) -> int:
    """用于把缺口闸门放行后仍存在的未判候选按 not_dialogue 显式落库（可见降级）

    2026-10-02 对齐 0.2.0：finish_chapter 收紧为"拒绝未判候选、不补造未判内容"，
    HEAD 时代"收尾时静默默认 + dialogue_defaulted 回执"的口径不能再进账本合同。
    降级改为编排层动作：逐条经生产单条事务边界写 not_dialogue（与降级指标同一条
    可见降级纪律——宁缺勿滥、留痕不伪装），返回条数供日志。
    """
    pending = ledger.dialogue_ledger()["pending"]
    for index in pending:
        entry = await _execute_call(
            {"name": "write_dialogue", "args": {"candidate_index": index, "verdict": "not_dialogue"},
             "id": f"subagents-default-{index}"},
            tool_map=tool_map,
            ledger=ledger,
            observer=None,
            stream=stream,
            call_index=0,
            program_meta={
                "program_id": "subagent_chapter",
                "op_index": 0,
                "source_line": None,
                "record": f"dialogue/{index}",
                "direct_fallback": False,
            },
        )
        if str(entry.get("status") or "error") != "success":
            logger.warning("未判候选默认判定落库失败 candidate={} receipt={}", index, entry.get("receipt"))
    if pending:
        logger.warning("本章有 {} 个候选经缺口闸门放行仍未判定，已按 not_dialogue 降级落库", len(pending))
    return len(pending)


async def _write_chapter_metrics(
    tool_map: dict[str, Any],
    ledger: AnnotationToolLedger,
    subagents: list[SubagentAnnotation],
    *,
    stream: Any | None,
) -> None:
    """用于把各 subagent 的段落标签与章级指标一次落库（缺指标时给中性兜底）

    段落标签与章级指标在生产面上同属 write_metrics 一个域（labels 是它的参数），
    所以标签不能在构造器里单独落库，统一收在这里一次写。指标缺提交时给中性兜底并把
    "缺失"写进摘要——绝不伪装成模型产出。指标已经落库、只是补标签失败时不整章失败
    （标签是软要求），但会留痕。
    """
    metric = None
    labels: dict[int, int] = {}
    for subagent in subagents:
        if subagent.metric is not None:
            metric = subagent.metric
        for item in subagent.labels:
            labels[item.paragraph_id] = item.emotion
    if metric is None:
        logger.warning("本章无 subagent 提交章级指标，章收尾按中性兜底补一条（摘要标为缺失）")
        args: dict[str, Any] = {
            "summary": _MISSING_METRIC_SUMMARY,
            "emotional_valence": 0,
            "narrative_function": "铺垫",
        }
    else:
        args = {
            "summary": metric.summary,
            "emotional_valence": metric.emotional_valence,
            "narrative_function": metric.narrative_function,
            "pivot_moment": metric.pivot_moment,
            "cliffhanger": metric.cliffhanger,
        }
    if labels:
        args["labels"] = [
            {"paragraph_id": paragraph_id, "emotion": labels[paragraph_id]} for paragraph_id in sorted(labels)
        ]
    entry = await _execute_call(
        {"name": "write_metrics", "args": args, "id": "subagents-metrics"},
        tool_map=tool_map,
        ledger=ledger,
        observer=None,
        stream=stream,
        call_index=0,
        program_meta={
            "program_id": "subagent_chapter",
            "op_index": 0,
            "source_line": None,
            "record": "metrics",
            "direct_fallback": False,
        },
    )
    if str(entry.get("status") or "error") == "success":
        return
    raw_receipt = entry.get("receipt")
    receipt: dict[str, Any] = raw_receipt if isinstance(raw_receipt, dict) else {}
    detail = str(receipt.get("message") or receipt.get("error") or entry.get("error") or "写入被拒")
    if ledger.metrics_payload is None:
        # 指标是收尾硬前提：这一笔没进去 finish 必被拒，整章失败（不静默）
        raise AnnotationRetryableError(f"章级指标落库失败: {detail}")
    logger.warning("章级标签补写失败（指标已在库）: {}", detail)


async def _settle_chapter(
    tool_map: dict[str, Any],
    ledger: AnnotationToolLedger,
    *,
    stream: Any | None,
) -> dict[str, Any]:
    """用于在章收尾相位末尾结算 finish（与程序面同一实现、同一冻结判定）"""
    entry = await _execute_call(
        {"name": "finish", "args": {}, "id": "subagents-finish"},
        tool_map=tool_map,
        ledger=ledger,
        observer=None,
        stream=stream,
        call_index=0,
        settle_finish=True,
        program_meta={
            "program_id": "subagent_chapter",
            "op_index": 0,
            "source_line": None,
            "record": "finish",
            "direct_fallback": False,
        },
    )
    raw_receipt = entry.get("receipt")
    receipt: dict[str, Any] = raw_receipt if isinstance(raw_receipt, dict) else {}
    if str(entry.get("status") or "error") != "success":
        detail = str(receipt.get("message") or receipt.get("error") or entry.get("error") or "收尾被拒")
        raise AnnotationRetryableError(f"多代理路径章级收尾失败: {detail}")
    return receipt


__all__ = [
    "run_chapter_subagents",
]
