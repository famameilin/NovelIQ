"""
章节标注 Agent 运行入口（agent 路径：单块章整章一个 agent）

2026-09-19 双路径定案：单块章走本入口（程序面，模型可见面=[execute_code, finish]），
多块章走 block_codeact.run_chapter_subagents 三条职责 subagent 并发；原生工具面
（模型直接 bind 写入工具）删除，程序面是两条路径唯一的模型可见面。
审计: 每次运行开启 agent_invocations 行（task_type="annotation"），模型回合与工具
调用通过 AgentTurnObserver 写入独立短事务；失败路径同样保留完整审计记录。
断流重试已下沉到 stream.py 当前模型请求层，章节不再整章重试。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from .errors import (
    AnnotationAgentError,
    AnnotationInputError,
    AnnotationRetryableError,
)
from .fact_graph import FactGraph
from .graph import build_annotation_graph
from .program import ProgramRuntime, build_program_tool
from .prompts import build_chapter_message, build_system_prompt
from .schema import AgentRunAudit, AgentRunResult, BoundChapterAnnotation, ChapterParagraphInfo
from .tools import (
    FINISH_TOOL_NAME,
    AnnotationQueryService,
    AnnotationToolLedger,
    build_annotation_tools,
)

if TYPE_CHECKING:
    from src.agents.audit.observer import AgentTurnObserver
    from src.agents.audit.recorder import AgentAuditRecorder
    from src.agents.stream import AgentStream


def _validate_chapter_identity(*, chapter_id: int, chapter_text: str) -> None:
    """2026-08-07 用于在模型调用前校验章节身份与正文非空

    2026-09-19 M9a-2 后章即块：一章一份正文（运行时块身份 = chapter_id），
    旧 current_chunks 列表协议随子块循环一起退役。
    """
    if chapter_id <= 0:
        raise AnnotationInputError("chapter_id 必须是真实非空正整数")
    if not chapter_text.strip():
        raise AnnotationInputError("章节正文不能为空")


def validate_bound_annotation(
    annotation: BoundChapterAnnotation,
    *,
    chapter_id: int,
    chapter_text: str,
    paragraph_info: ChapterParagraphInfo | None = None,
) -> None:
    """2026-08-07 用于复核系统绑定标注完整覆盖章正文和对话原文

    2026-08-18：增加事件锚点校验——每个事件的 char_start/char_end 必须落在
    章正文范围内。
    2026-09-14 段落级监督：自选段标签复核改段落号归属（账本写入点已按
    paragraph_info 校验；此处给段落坐标映射时做同一不变量的二次校验，
    替代旧"句文本逐字区间"复核——段号没有逐字复核的对象）。
    2026-09-19 章即块拍平：绑定标注就是章本身，chapter_id 即章身份；
    block_codeact 的章收尾用同一签名。
    """
    if chapter_id <= 0:
        raise AnnotationInputError("chapter_id 必须为正整数")
    for dialogue in annotation.dialogues:
        if dialogue.end > len(chapter_text):
            raise ValueError(f"系统对话位置超出原文: chapter_id={chapter_id}")
        actual = chapter_text[dialogue.start : dialogue.end]
        if actual != dialogue.content:
            raise ValueError(f"系统对话原文绑定不一致: chapter_id={chapter_id}")
    if paragraph_info is not None:
        known_paragraph_ids = set(paragraph_info.paragraph_ids)
        for label in annotation.paragraph_labels:
            if label.paragraph_id not in known_paragraph_ids:
                raise ValueError(
                    f"系统自选段标签超出本章段落范围: chapter_id={chapter_id}"
                    f" paragraph_id={label.paragraph_id}"
                )
    # 2026-08-22 重构：事件不再携带锚点/字符区间/哈希，章级证据由持久化层盖章


def _model_provider(llm: Any) -> str:
    """2026-08-05 用于从模型地址稳定区分本地与云端审计来源"""
    raw_base_url = getattr(llm, "base_url", "") or getattr(llm, "openai_api_base", "") or ""
    base_url = str(raw_base_url)
    if base_url and "localhost" not in base_url and "127.0.0.1" not in base_url:
        return "cloud"
    return "local"


def _model_name(llm: Any) -> str | None:
    """2026-08-10 用于从模型对象稳定读取审计用模型名"""
    return str(getattr(llm, "model_name", None) or getattr(llm, "model", "") or None) or None


async def _run_single_attempt(
    *,
    run_id: str,
    chapter_id: int,
    attempt_number: int,
    chapter_text: str,
    novel_title: str | None,
    llm: Any,
    session_factory: Callable[[], Session],
    query_service_factory: Callable[[Callable[[], Session]], AnnotationQueryService],
    stream: AgentStream | None = None,
    graph_state: FactGraph | None = None,
    observer: AgentTurnObserver | None = None,
    paragraph_info: ChapterParagraphInfo | None = None,
) -> AgentRunResult:
    """2026-08-10 用于以全新账本执行一次章节 Agent 尝试（程序面）

    2026-09-19 恢复写者程序面并去开关：绑定面=[execute_code, finish]（与 subagent 面
    同形；finish 既是绑定工具也可写在程序末尾，两条通道同一条收尾判定），分发面仍是
    完整工具表（含程序工具自身），模型直发原生调用时由批次转入同一个内层
    dispatcher（见 graph 批次节点）；章正文整章注入（章即块，不再有子块协议）。
    2026-09-16 连接粒度：这里不再自己开只读会话，只把 session_factory 转交查询服务，
    由它在单次工具调用内取还连接（模型生成期间连接占用为零）。
    """
    from src.config import settings

    query_service = query_service_factory(session_factory)
    allow_future_context = settings.models.annotation.allow_future_context
    ledger = AnnotationToolLedger(
        run_scope=run_id,
        current_chapter_id=chapter_id,
        current_chapter_text=chapter_text,
        allow_future_context=allow_future_context,
        graph=graph_state,
        paragraph_info=paragraph_info,
        # 2026-08-19供因果引用全局偏序校验使用
        current_chapter_order=getattr(query_service, "current_chapter_order", None),
    )
    tools = build_annotation_tools(query_service, ledger)
    finish_tool = {str(tool.name): tool for tool in tools}[FINISH_TOOL_NAME]
    program_tool = build_program_tool(ProgramRuntime(tools, ledger, observer=observer, stream=stream))
    total_iteration_limit = max(1, settings.models.annotation.max_iterations)
    graph = build_annotation_graph(
        llm,
        [*tools, program_tool],
        ledger=ledger,
        max_iterations=total_iteration_limit,
        stream=stream,
        observer=observer,
        retries=settings.models.annotation.total_attempts,
        bind_tools=[program_tool, finish_tool],
        program_tool_name=str(program_tool.name),
    )
    initial_messages = [
        SystemMessage(content=build_system_prompt()),
        HumanMessage(
            content=build_chapter_message(
                chapter_text=chapter_text,
                candidates=ledger.dialogue_candidates,
                paragraph_info=paragraph_info,
            )
        ),
    ]
    result_state = await graph.ainvoke(
        {
            "messages": initial_messages,
            "phase": "chapter_open",
            "iterations": 0,
            "error": None,
        }
    )
    error = result_state.get("error")
    if error:
        raise AnnotationRetryableError(str(error))
    if result_state.get("phase") != "completed" or ledger.annotation is None:
        raise AnnotationRetryableError("annotation LangGraph 未正常完成章节")

    validate_bound_annotation(
        ledger.annotation,
        chapter_id=chapter_id,
        chapter_text=chapter_text,
        paragraph_info=paragraph_info,
    )
    return AgentRunResult(
        run_id=run_id,
        chapter_id=chapter_id,
        annotation=ledger.annotation,
        resolved_cases=list(ledger.resolved_cases),
        pushed_cases=list(ledger.pushed_cases),
        audit=AgentRunAudit(
            allow_future_context=allow_future_context,
            write_records=list(ledger.write_records),
            authorized_chapter_ids=sorted(ledger.authorized_chapter_ids),
            authorized_text_paragraph_ids=sorted(ledger.authorized_text_paragraph_ids),
            authorized_event_ids=sorted(ledger.authorized_event_ids),
        ),
    )


async def run_annotation_agent(
    *,
    run_id: str,
    chapter_id: int,
    chapter_text: str,
    query_service_factory: Callable[[Callable[[], Session]], AnnotationQueryService],
    session_factory: Callable[[], Session],
    novel_title: str | None = None,
    novel_id: str = "default",
    llm: Any | None = None,
    stream: AgentStream | None = None,
    graph_state: FactGraph | None = None,
    audit_recorder: AgentAuditRecorder | None = None,
    chapter_label: str | None = None,
    paragraph_info: ChapterParagraphInfo | None = None,
) -> AgentRunResult:
    """2026-08-11 用于单次运行章节 Agent（agent 路径）：断流重试已下沉到 stream.py，章节失败直接抛出

    2026-09-19 双路径定案：本入口服务单块章（整章正文一次注入），多块章由派发方
    走 run_chapter_subagents；签名从 current_chunks 列表改为章正文。
    2026-09-16 连接粒度：不再自开只读会话，查询服务按单次工具调用取还连接。
    """
    from src.agents.audit.observer import AgentTurnObserver
    from src.agents.audit.recorder import AgentAuditRecorder

    _validate_chapter_identity(
        chapter_id=chapter_id,
        chapter_text=chapter_text,
    )
    if llm is None:
        from src.agents.llm import build_chat_model

        llm = build_chat_model("annotation")

    recorder = audit_recorder or AgentAuditRecorder(session_factory)
    model_name = _model_name(llm)
    model_provider = _model_provider(llm)
    if graph_state is not None:
        graph_state.begin_chapter()
    invocation_id = recorder.start_invocation(
        run_id=run_id,
        task_type="annotation",
        chapter_id=chapter_id,
        attempt_number=1,
        model_name=model_name,
        model_provider=model_provider,
    )
    observer = AgentTurnObserver(
        recorder,
        invocation_id=invocation_id,
        run_id=run_id,
        novel_id=novel_id,
        task_type="annotation",
        call_type="agent",
        model_name=model_name or "unknown",
        model_provider=model_provider,
    )
    if stream is not None:
        await stream.thinking(f"章节 {chapter_label or chapter_id} 标注开始")
    try:
        result = await _run_single_attempt(
            run_id=run_id,
            chapter_id=chapter_id,
            attempt_number=1,
            chapter_text=chapter_text,
            novel_title=novel_title,
            llm=llm,
            session_factory=session_factory,
            query_service_factory=query_service_factory,
            stream=stream,
            graph_state=graph_state,
            observer=observer,
            paragraph_info=paragraph_info,
        )
    except Exception as exc:
        if graph_state is not None:
            # 章节失败时恢复事实图历史快照，避免当章脏状态残留到后续章节
            graph_state.reset_chapter_changes()
        recorder.finish_invocation(invocation_id, status="error", final_error=str(exc))
        raise
    # 2026-09-04 单一写面：取出本章累积的图域操作日志随结果返回，
    # 由 workflow 合并进完成事务输入（失败路径已在上方 reset 清空）
    if graph_state is not None:
        result = result.model_copy(update=graph_state.drain_ops())
    recorder.finish_invocation(invocation_id, status="success")
    if stream is not None:
        await stream.output(f"章节 {chapter_label or chapter_id} 标注完成")
    return result


__all__ = [
    "AnnotationAgentError",
    "AgentRunResult",
    "run_annotation_agent",
    "validate_bound_annotation",
]
