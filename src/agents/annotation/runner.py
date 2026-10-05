"""正式章节 Agent 执行入口，断流重试位于模型请求层"""

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
from .event_submission import build_event_submission_tool
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
    正式信封使用同一验证边界。
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
    """以独立本章图执行正式工具，查询连接仅在实际读取期间持有"""
    from src.config import settings

    query_service = query_service_factory(session_factory)
    if graph_state is not None:
        graph_state.chapter_id = chapter_id
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
    runtime = ProgramRuntime(tools, ledger, observer=observer, stream=stream)
    program_tool = build_program_tool(runtime)
    event_submission_tool = build_event_submission_tool(runtime)
    total_iteration_limit = max(1, settings.models.annotation.max_iterations)
    graph = build_annotation_graph(
        llm,
        [*tools, program_tool, event_submission_tool],
        ledger=ledger,
        max_iterations=total_iteration_limit,
        stream=stream,
        observer=observer,
        retries=settings.models.annotation.total_attempts,
        bind_tools=[program_tool, event_submission_tool, finish_tool],
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
        pushed_cases=list(ledger.pushed_cases),
        cross_chapter_links=list(ledger.cross_chapter_links),
        audit=AgentRunAudit(
            allow_future_context=allow_future_context,
            write_records=list(ledger.write_records),
            authorized_text_paragraph_ids=sorted(ledger.authorized_text_paragraph_ids),
            source_anchors=ledger.source_anchors,
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
    """正式章节的唯一模型入口，工作成功后返回不可变提交载荷"""
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
    graph_snapshot = graph_state.snapshot() if graph_state is not None else None
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
        if graph_state is not None and graph_snapshot is not None:
            graph_state.restore(graph_snapshot)
        recorder.finish_invocation(invocation_id, status="error", final_error=str(exc))
        raise
    # 本章局部命令与标注一同进入正式不可变提交
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
