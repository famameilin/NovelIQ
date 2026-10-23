"""
Agent 流式事件封装

将 Agent 循环中的模型推理/工具调用过程翻译为统一 StreamEvent 并发送到 SSE，
Agent 层只需持有 AgentStream 即可获得完整过程可见性。

所有 LLM 调用统一经 astream 聚合（模型实例由 llm.py 以 streaming=True 构建）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from httpx import HTTPError
from langchain_core.messages import AIMessage, HumanMessage
from openai import APIError

from src.agents.stream_aggregator import (
    StreamChunkAggregator,
)
from src.agents.stream_audit import ModelCallTiming, _provider_request_metadata
from src.agents.stream_errors import StreamEmitError
from src.event_bus.notifications import StreamEvent, StreamEventAction

_MAX_TOOL_SUMMARY_CHARS = 200

# 内容进度看门狗阈值（秒）：流块到达而内容零增长超过该值即判死重发。
# 层级不变量：本看门狗必须低于 llm.py 的 httpx 读超时（180s）。
CONTENT_STALL_TIMEOUT_S = 150.0

logger = logging.getLogger(__name__)


class ModelRequestError(RuntimeError):
    """模型请求处理结束后的服务故障，交给模型池重新选举"""


# 瞬态错误类型名标记：openai/httpx 网络与限流异常按类名匹配
_TRANSIENT_ERROR_MARKERS = (
    "timeout",
    "connection",
    "connect",
    "ratelimit",
    "rate_limit",
    "429",
    "remoteprotocol",
)

# 迭代中被并发变更为竞态形态（消息匹配而非类名）：同请求重发大概率即愈。
_RACE_ITERATION_MESSAGES = (
    "dictionary changed size during iteration",
    "dictionary keys changed during iteration",
    "deque mutated during iteration",
)


class ContentStallTimeoutError(TimeoutError):
    """用于标注"连接活着但内容零增长"的僵流形态

    判活信号为内容增量本身（reasoning/content/tool_calls）；继承 TimeoutError
    以落进 _is_transient_model_error 的既有重发通道。
    """

    def __init__(self, timeout_s: float, chunks_seen: int, content_chunks: int, elapsed_s: float) -> None:
        self.timeout_s = timeout_s
        self.chunks_seen = chunks_seen
        self.content_chunks = content_chunks
        self.elapsed_s = elapsed_s
        super().__init__(
            f"内容进度停摆 {timeout_s:.0f}s（收到 {chunks_seen} 个流块，其中内容块 {content_chunks} 个，"
            f"历时 {elapsed_s:.0f}s）：连接可能活着但生成端无产出"
        )


def _chunk_has_content(chunk: Any) -> bool:
    """用于判定流块是否携带实际内容（内容进度看门狗的判活信号）"""
    content = getattr(chunk, "content", None)
    if isinstance(content, str) and content:
        return True
    if isinstance(content, list) and any(isinstance(part, dict) and part.get("text") for part in content):
        return True
    kwargs = getattr(chunk, "additional_kwargs", None) or {}
    return bool(
        kwargs.get("reasoning_content")
        or kwargs.get("function_call")
        or getattr(chunk, "tool_call_chunks", None)
        or getattr(chunk, "tool_calls", None)
    )


async def _guard_content_progress(source: Any, timeout_s: float) -> Any:
    """内容进度看门狗：流块持续到达而内容零增长超过 timeout_s 即判死

    从流开始即武装，每个内容帧重置计时。提前退出（判死/取消）时显式
    aclose 底层流，及时释放 HTTP 连接。
    """
    if timeout_s <= 0:
        async for chunk in source:
            yield chunk
        return
    started = time.monotonic()
    last_content = started
    chunks_seen = 0
    content_chunks = 0
    iterator = source.__aiter__()
    try:
        while True:
            remaining = timeout_s - (time.monotonic() - last_content)
            if remaining <= 0:
                raise ContentStallTimeoutError(timeout_s, chunks_seen, content_chunks, time.monotonic() - started)
            try:
                chunk = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
            except StopAsyncIteration:
                return
            except TimeoutError as exc:
                # wait_for 在预算耗尽处判死（保活帧形态下这是主要触发点，而非预检查）
                raise ContentStallTimeoutError(
                    timeout_s, chunks_seen, content_chunks, time.monotonic() - started
                ) from exc
            chunks_seen += 1
            if _chunk_has_content(chunk):
                content_chunks += 1
                last_content = time.monotonic()
            yield chunk
    finally:
        aclose = getattr(source, "aclose", None)
        if aclose is not None:
            with contextlib.suppress(Exception):
                await aclose()


CompletionHintProvider = Callable[[], str | None]
"""无工具回复重发前向本次请求注入的提示工厂

返回 None 表示不注入（调用方无上下文可提示）。提示会追加进重发的 messages
列表（调用方须传自有副本），使重试物理请求的审计 request_messages 与实发一致；
不写入 LangGraph 状态消息链。
"""


def _is_transient_model_error(exc: BaseException) -> bool:
    """用于判定网络/限流类瞬态错误：仅这类错误值得重发模型请求

    覆盖内置 ConnectionError/TimeoutError 以及 openai/httpx 异常类型
    （APIConnectionError/APITimeoutError/RateLimitError/ConnectError/ReadTimeout/
    RemoteProtocolError 等）；httpx 本地协议错误不在此列。
    """
    # 配额错误不在调用层原地重发，交给模型池处理
    code = _model_error_code(exc)
    if code in {"AccountQuotaExceeded", "QuotaExceeded", "SetLimitExceeded"} or code.startswith("QuotaExceeded."):
        return False
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    if isinstance(exc, RuntimeError) and any(marker in str(exc) for marker in _RACE_ITERATION_MESSAGES):
        return True
    name = type(exc).__name__.lower()
    return any(marker in name for marker in _TRANSIENT_ERROR_MARKERS)


def _model_error_code(exc: BaseException) -> str:
    """读取 SDK 的结构化错误码，支持直接错误体及带 error 的响应体"""
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    body = getattr(exc, "body", None)
    if isinstance(body, Mapping):
        error = body.get("error", body)
        if isinstance(error, Mapping):
            return str(error.get("code") or "")
    return ""


def _retry_after_seconds(exc: BaseException) -> float | None:
    """读取服务端 429 响应的 Retry-After 头（秒数或 HTTP 日期），无法解析返回 None"""
    from datetime import UTC, datetime
    from email.utils import parsedate_to_datetime

    headers = getattr(getattr(exc, "response", None), "headers", None)
    raw = headers.get("Retry-After") if headers is not None else None
    if raw is None:
        return None
    try:
        seconds = float(raw)
        return seconds if math.isfinite(seconds) and seconds >= 0 else None
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(str(raw))
        except (TypeError, ValueError):
            return None
        if date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
        return max(0.0, (date - datetime.now(UTC)).total_seconds())


def _retry_backoff_seconds(attempt: int, exc: BaseException | None = None) -> float:
    """频率限流遵守服务端冷却时间，缺失时等待 60、120 秒

    attempt 从 1 起计；429 最多在原回合重试两次，不截短 Retry-After。
    其他瞬态故障及无工具回复按 1、2、3 秒封顶退避。
    """
    backoff = min(0.5 * (2 ** max(attempt, 1)), 3.0)
    if exc is not None:
        status = getattr(exc, "status_code", None)
        if status is None:
            status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 429:
            retry_after = _retry_after_seconds(exc)
            if retry_after is not None:
                return retry_after
            return 60.0 * min(max(attempt, 1), 2)
    return backoff


def _is_call_complete(message: Any) -> bool:
    """用于判定一次模型调用是否正常结束：响应包含至少一个工具调用

    本项目所有 agent（标注/诊断）的有效产出均经工具调用产生，纯文本回复不推进任何状态。
    """
    return bool(getattr(message, "tool_calls", None))


def _truncate(text: str, limit: int = _MAX_TOOL_SUMMARY_CHARS) -> str:
    """截断过长摘要，避免工具结果刷爆事件负载"""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


class AgentStream:
    """
    Agent 过程事件封装

    职责:
    1. 包装 emitter，提供 thinking/output/工具调用事件的便捷方法
    2. stage 等上下文由事件总线自动补全，本类只负责 action/content
    """

    def __init__(
        self,
        emitter: Callable[[StreamEvent], Awaitable[None]],
        *,
        chapter_id: int = 0,
        sub_stage: str = "",
        stream_id: str | None = None,
    ) -> None:
        self._emitter = emitter
        self._chapter_id = chapter_id
        self._sub_stage = sub_stage
        self._stream_id = stream_id or f"{sub_stage or 'agent'}-{chapter_id}"

    async def thinking(self, text: str) -> None:
        """发送实际推理内容或调用状态文字"""
        await self._emit("thinking", text)

    async def output(self, text: str) -> None:
        """发送模型正式输出事件"""
        await self._emit("output", text)

    async def tool_call_started(self, name: str, args_summary: str = "", *, tool_call_id: str = "") -> None:
        """发送工具调用开始事件"""
        message = f"正在调用工具 {name}"
        if args_summary:
            message = f"{message}：{args_summary}"
        await self._emit_tool(name, "started", message, tool_call_id)

    async def tool_call_succeeded(self, name: str, summary: str = "", *, tool_call_id: str = "") -> None:
        """发送工具执行成功事件"""
        message = f"工具 {name} 执行成功"
        if summary:
            message = f"{message}：{_truncate(summary)}"
        await self._emit_tool(name, "success", message, tool_call_id)

    async def tool_call_failed(self, name: str, error: str = "", *, tool_call_id: str = "") -> None:
        """发送工具执行失败事件"""
        message = f"工具 {name} 执行失败"
        if error:
            message = f"{message}：{_truncate(error)}"
        await self._emit_tool(name, "failed", message, tool_call_id)

    async def _emit(self, action: StreamEventAction, text: str) -> None:
        if not text:
            return
        await self._emitter(
            StreamEvent(
                action=action,
                content=text,
                chapter_id=self._chapter_id,
                sub_stage=self._sub_stage,
                stream_id=self._stream_id,
            )
        )

    async def _emit_tool(self, name: str, status: str, message: str, tool_call_id: str) -> None:
        await self._emitter(
            StreamEvent(
                action="tool_call",
                tool_call_id=tool_call_id,
                content=name,
                message=message,
                status=status,
                chapter_id=self._chapter_id,
                sub_stage=self._sub_stage,
                stream_id=self._stream_id,
            )
        )


def _format_turn_error(exc: BaseException) -> str:
    """用于审计 error 列恒带异常类型前缀：str(exc) 为空时审计只剩空串不可诊断"""
    return f"{type(exc).__name__}: {exc}"


async def run_model_call(
    model: Any,
    messages: list[Any],
    stream: AgentStream | None,
    *,
    on_turn_complete: Callable[[AIMessage, ModelCallTiming], None] | None = None,
    on_turn_started: Callable[[dict[str, Any], int], None] | None = None,
    on_turn_failed: Callable[[str, ModelCallTiming, AIMessage | None], None] | None = None,
    total_attempts: int | None = None,
    completion_hint: CompletionHintProvider | None = None,
    require_tool_call: bool = True,
    content_stall_timeout_s: float | None = None,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> AIMessage:
    """流式请求模型并按物理请求记录审计，服务故障交回模型池

    total_attempts 只约束当前请求重发；SSE、审计与项目自身异常直接上抛
    """
    from src.config import settings

    total_attempts = total_attempts if total_attempts is not None else settings.models.annotation.total_attempts

    hint_resolved = False

    def _apply_completion_hint() -> None:
        """首次无工具回复时向重发请求注入一次提示（原地追加调用方副本）"""
        nonlocal hint_resolved
        if hint_resolved or completion_hint is None:
            return
        hint_resolved = True
        hint = completion_hint()
        if hint:
            messages.append(HumanMessage(content=hint))
            logger.warning("无工具回复重发前注入补齐提示: hint_chars=%s", len(hint))

    retries_remaining = max(0, total_attempts - 1)
    skip_output_prefix = ""
    announced_tools: set[str] = set()
    attempt = 0
    rate_limit_retries = 0
    while True:
        attempt += 1
        started_ns = clock_ns()
        if on_turn_started is not None:
            on_turn_started(_provider_request_metadata(model, attempt=attempt), started_ns)
        aggregator = StreamChunkAggregator(
            stream,
            started_ns=started_ns,
            clock_ns=clock_ns,
            skip_output_prefix=skip_output_prefix,
            announced_tools=announced_tools,
        )
        try:
            stall_timeout = CONTENT_STALL_TIMEOUT_S if content_stall_timeout_s is None else content_stall_timeout_s
            async for chunk in _guard_content_progress(model.astream(messages), stall_timeout):
                await aggregator.add_chunk(chunk)
            response = aggregator.finish()
        except StreamEmitError as exc:
            # 客户端已断开，重试推送也发不出去，直接上抛不再重发模型请求
            if on_turn_failed is not None:
                on_turn_failed(_format_turn_error(exc), aggregator.timing(), aggregator.finish())
            raise
        except Exception as exc:
            if on_turn_failed is not None:
                on_turn_failed(_format_turn_error(exc), aggregator.timing(), aggregator.finish())
            status = getattr(exc, "status_code", None)
            if status is None:
                status = getattr(getattr(exc, "response", None), "status_code", None)
            rate_limited = status == 429
            if (
                retries_remaining <= 0
                or not _is_transient_model_error(exc)
                or (rate_limited and rate_limit_retries >= 2)
            ):
                logger.warning("模型输出流中断且重试耗尽: error=%r", exc, exc_info=True)
                if isinstance(exc, (APIError, HTTPError, ConnectionError, TimeoutError)) or _is_transient_model_error(
                    exc
                ):
                    raise ModelRequestError(_format_turn_error(exc)) from exc
                raise
            failed_attempt = total_attempts - retries_remaining
            retries_remaining -= 1
            if rate_limited:
                rate_limit_retries += 1
            delay = _retry_backoff_seconds(rate_limit_retries if rate_limited else failed_attempt, exc)
            logger.warning(
                "模型请求失败，等待 %s 秒后重发当前回合: error=%r retries_remaining=%s",
                delay,
                exc,
                retries_remaining,
                exc_info=True,
            )
            if stream is not None:
                if rate_limited:
                    await stream.thinking(
                        f"模型请求触发限流，等待 {delay:g} 秒后重试当前回合"
                        f"（剩余 {min(retries_remaining, 3 - rate_limit_retries)} 次）"
                    )
                else:
                    await stream.thinking(f"模型输出流中断，正在重试当前请求（剩余 {retries_remaining} 次）")
            skip_output_prefix = "".join(aggregator._content_parts)
            announced_tools = set(aggregator._announced_tools)
            # 异步等待不推进模型轮次、不执行工具，阶段取消仍能立即打断
            await asyncio.sleep(delay)
            continue
        timing = aggregator.timing()
        # 调用未正常结束（响应不含工具调用）视同调用层故障：退避重发同一请求，
        # 耗尽后上抛交由上层失败审计收口；
        # require_tool_call=False 时无工具回复即上报完毕，正常返回
        if require_tool_call and not _is_call_complete(response):
            error = "模型调用未正常结束：响应未包含任何工具调用"
            if on_turn_failed is not None:
                on_turn_failed(error, timing, response)
            if retries_remaining <= 0:
                logger.warning("模型调用未正常结束且重试已耗尽")
                raise ModelRequestError(f"{error}，重发后仍未恢复")
            failed_attempt = total_attempts - retries_remaining
            retries_remaining -= 1
            _apply_completion_hint()
            logger.warning(
                "模型调用未正常结束（响应不含工具调用），重发当前模型请求: retries_remaining=%s",
                retries_remaining,
            )
            skip_output_prefix = "".join(aggregator._content_parts)
            announced_tools = set(aggregator._announced_tools)
            if stream is not None:
                await stream.thinking(f"模型调用未正常结束，正在重试当前请求（剩余 {retries_remaining} 次）")
            await asyncio.sleep(_retry_backoff_seconds(failed_attempt))
            continue
        if on_turn_complete is not None:
            on_turn_complete(response, timing)
        return response


async def emit_tool_results(stream: AgentStream, tool_messages: list[Any]) -> None:
    """
    为工具执行结果批量发送成功/失败事件

    ToolNode 会把异常封装进 ToolMessage.content，按文本启发式区分成败
    """
    for message in tool_messages:
        name = getattr(message, "name", "") or "unknown"
        content = getattr(message, "content", "") or ""
        text = str(content)
        is_failed = text.startswith("Error:") or '"error"' in text or "执行失败" in text or "校验失败" in text
        if is_failed:
            await stream.tool_call_failed(name, text, tool_call_id=getattr(message, "tool_call_id", ""))
        else:
            await stream.tool_call_succeeded(name, text, tool_call_id=getattr(message, "tool_call_id", ""))


__all__ = [
    "AgentStream",
    "emit_tool_results",
    "run_model_call",
]
