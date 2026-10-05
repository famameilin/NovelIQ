"""
Agent 流式事件封装

将 Agent 循环中的模型推理/工具调用过程翻译为统一 StreamEvent 并发送到 SSE，
Agent 层只需持有 AgentStream 即可获得完整过程可见性。

计时说明: 2026-10-02 删除"流式输出"设置后所有 LLM 调用固定走流式
（llm.py 以 streaming=True 构建模型实例），本模块统一经 astream 聚合，
流式 Provider 得到真实 TTFT。

拆分说明: 2026-10-02 审计脱敏与请求元数据迁至 stream_audit.py，chunk 纯
函数与聚合器迁至 stream_aggregator.py；本模块保留 re-export 面（含
ModelCallTiming/StreamChunkAggregator/extract_reasoning_content 等），
导入方零改动，`__all__` 面不变。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.stream_aggregator import (
    StreamChunkAggregator,
)
from src.agents.stream_aggregator import (
    _merge_tool_call_chunks as _merge_tool_call_chunks,
)
from src.agents.stream_aggregator import (
    extract_reasoning_content as extract_reasoning_content,
)
from src.agents.stream_audit import ModelCallTiming, _provider_request_metadata
from src.api.models.events import StreamEvent, StreamEventAction

_MAX_TOOL_SUMMARY_CHARS = 200

# 2026-10-04 内容进度看门狗阈值（秒）：流块到达而内容零增长超过该值即判死重发。
# 依据：run 4cb054dc 末章僵流 31 分钟零内容（保活帧喂活了全部"有块"信号）；
# 本 run 132 个计量回合 TTFT p99=9.4s/max=9.9s，重放健康流 ~57 内容帧/秒；
# llm.py 注释声称的"网关限流队列/思考停顿超 2 分钟"远低于该阈值。
# 误判代价=一次重发（total_attempts 兜底），漏判代价=lane 挂死需人工重启。
CONTENT_STALL_TIMEOUT_S = 300.0

logger = logging.getLogger(__name__)

perf_counter_ns = time.perf_counter_ns

# 2026-08-13 P2-6 瞬态错误类型名标记：openai/httpx 网络与限流异常按类名匹配
_TRANSIENT_ERROR_MARKERS = (
    "timeout",
    "connection",
    "connect",
    "ratelimit",
    "rate_limit",
    "429",
)


class StreamEmitError(RuntimeError):
    """2026-08-12 用于区分 SSE 推送失败与模型输出流中断：推送失败不触发模型请求重试"""


class ContentStallTimeoutError(TimeoutError):
    """2026-10-04 用于标注"连接活着但内容零增长"的僵流形态

    run 4cb054dc 末章实测：Provider 对单个请求卡死生成后仍持续下发可解析
    保活帧（31 分钟零内容），httpx 读超时(120s)与 langchain 解析块看门狗
    (600s)都以"有块到达"为信号被喂活，不会触发。本看门狗的判活信号改为
    内容增量本身（reasoning/content/tool_calls）；继承 TimeoutError 以落进
    _is_transient_model_error 的既有重发通道。健康流内容密度实测 ~57 帧/秒
    （重放 turn 886：24775 内容帧/433s，唯一空 delta 是 finish 帧），阈值
    300s 有数十倍边际；真实误判代价=一次重发，漏判代价=lane 挂死需人工重启。
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
    """2026-10-04 用于判定流块是否携带实际内容（内容进度看门狗的判活信号）"""
    content = getattr(chunk, "content", None)
    if isinstance(content, str) and content:
        return True
    if isinstance(content, list) and any(
        isinstance(part, dict) and part.get("text") for part in content
    ):
        return True
    kwargs = getattr(chunk, "additional_kwargs", None) or {}
    return bool(
        kwargs.get("reasoning_content")
        or kwargs.get("function_call")
        or getattr(chunk, "tool_call_chunks", None)
        or getattr(chunk, "tool_calls", None)
    )


async def _guard_content_progress(source: Any, timeout_s: float) -> Any:
    """2026-10-04 内容进度看门狗：流块持续到达而内容零增长超过 timeout_s 即判死

    与 langchain 的 stream_chunk_timeout（解析块间隔）互补：后者会被可解析
    保活帧喂活而失效（mock 复现变体 B 坐实）。从流开始即武装——事故形态正是
    首个内容帧永不到来；每个内容帧重置计时。提前退出（判死/取消）时显式
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
                raise ContentStallTimeoutError(
                    timeout_s, chunks_seen, content_chunks, time.monotonic() - started
                )
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
"""2026-09-08 无工具回复重发前向本次请求注入的提示工厂

返回 None 表示不注入（调用方无上下文可提示）。提示会追加进重发的 messages
列表（调用方须传自有副本），使重试物理请求的审计 request_messages 与实发一致；
不写入 LangGraph 状态消息链，与 09-05 轮次预算提醒同构。
"""


def _is_transient_model_error(exc: BaseException) -> bool:
    """2026-08-13 P2-6 用于判定网络/限流类瞬态错误：仅这类错误值得重发模型请求

    覆盖内置 ConnectionError/TimeoutError 以及 openai/httpx 异常类型
    （APIConnectionError/APITimeoutError/RateLimitError/ConnectError/ReadTimeout 等）。
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    name = type(exc).__name__.lower()
    return any(marker in name for marker in _TRANSIENT_ERROR_MARKERS)


def _retry_after_seconds(exc: BaseException) -> float | None:
    """读取服务端 429 响应的 Retry-After 头（秒数或 HTTP 日期），无法解析返回 None"""
    from datetime import UTC, datetime
    from email.utils import parsedate_to_datetime

    headers = getattr(getattr(exc, "response", None), "headers", None)
    raw = headers.get("Retry-After") if headers is not None else None
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(str(raw))
        except (TypeError, ValueError):
            return None
        if date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
        return max(0.0, (date - datetime.now(UTC)).total_seconds())


def _retry_backoff_seconds(attempt: int, exc: BaseException | None = None) -> float:
    """2026-08-13 P2-12 用于计算重试前退避时长：0.5s × 2^attempt 指数退避，上限 3s

    attempt 从 1 起计（第一次重试前等待 1s，第二次 2s，第三次 3s 封顶）。
    仅对 429/连接类瞬态错误生效，其余错误不额外等待。
    2026-10-03 429 退避归本模块管（permit 层已删）：服务端给了 Retry-After 时取
    max(指数退避, Retry-After)，上限放宽到 30s，避免压垮限流网关。
    """
    backoff = min(0.5 * (2 ** max(attempt, 1)), 3.0)
    if exc is not None:
        status = getattr(exc, "status_code", None)
        if status is None:
            status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 429:
            retry_after = _retry_after_seconds(exc)
            if retry_after is not None:
                return min(max(backoff, retry_after), 30.0)
    return backoff


def _is_call_complete(message: Any) -> bool:
    """2026-08-22 用于判定一次模型调用是否正常结束：响应包含至少一个工具调用

    本项目所有 agent（标注/诊断）的有效产出均经工具调用产生，纯文本回复不推进任何状态。
    网关在思考阶段静默截断流式响应时，聚合结果正是"仅推理、无正文、无工具调用"的空回复；
    该形态与断流统一走调用层重发，不再进入上层协议处理，避免传输故障冒充模型行为问题。
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
        """发送思考/推理状态事件（仅状态消息，不推送推理 token 内容）"""
        await self._emit("thinking", text)

    async def output(self, text: str) -> None:
        """发送模型正式输出事件"""
        await self._emit("output", text)

    async def tool_call_started(self, name: str, args_summary: str = "") -> None:
        """发送工具调用开始事件"""
        message = f"正在调用工具 {name}"
        if args_summary:
            message = f"{message}：{args_summary}"
        await self._emit_tool(name, "started", message)

    async def tool_call_succeeded(self, name: str, summary: str = "") -> None:
        """发送工具执行成功事件"""
        message = f"工具 {name} 执行成功"
        if summary:
            message = f"{message}：{_truncate(summary)}"
        await self._emit_tool(name, "success", message)

    async def tool_call_failed(self, name: str, error: str = "") -> None:
        """发送工具执行失败事件"""
        message = f"工具 {name} 执行失败"
        if error:
            message = f"{message}：{_truncate(error)}"
        await self._emit_tool(name, "failed", message)

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

    async def _emit_tool(self, name: str, status: str, message: str) -> None:
        await self._emitter(
            StreamEvent(
                action="tool_call",
                content=name,
                message=message,
                status=status,
                chapter_id=self._chapter_id,
                sub_stage=self._sub_stage,
                stream_id=self._stream_id,
            )
        )


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
) -> AIMessage:
    """
    调用模型并返回完整 AIMessage

    2026-10-02 删除"流式输出"设置后统一走 astream 流式聚合并推送事件
    （模型实例由 llm.py 以 streaming=True 构建，非流式兜底分支已删除）。
    流式输出中途断流（astream 抛异常）时用同一 messages 重发当前模型请求，
    total_attempts 表示总调用次数（重试次数 = total_attempts - 1），
    total_attempts=1 时关闭重试；缺省对齐 settings.models.annotation.total_attempts
    （默认 3 次，即最多重试 2 次）；
    重试期间推送 thinking 事件，并跳过与上次已推送内容重叠的前缀，避免重复输出；
    已失败尝试的用量与最终用量分别交给物理请求审计记账，避免跨请求混合。
    耗尽后抛出最后一次异常。SSE 推送失败（StreamEmitError）不触发重试。
    网络/限流等瞬态错误（_is_transient_model_error）与"响应不含任何工具调用"
    均按调用层故障共用 total_attempts 预算退避重发（2026-08-22），耗尽后上抛
    RuntimeError；参数/鉴权等确定性错误直接失败。
    2026-10-04 流消费经内容进度看门狗包装（_guard_content_progress）："流块
    持续到达而内容零增长"超过 content_stall_timeout_s（缺省
    CONTENT_STALL_TIMEOUT_S=300s，0/负值关闭）判死为 ContentStallTimeoutError，
    按瞬态错误走同一重发预算；用于兜住保活帧喂活解析块看门狗的僵流形态。
    2026-09-08 无工具回复重发前调用 completion_hint 工厂取提示（整个 run_model_call
    周期内只取一次、只注入一次——重试间隔内无工具执行，账本状态不会变化），
    追加进重发请求让模型看到缺域清单；工厂缺省或返回 None 时维持原样重发。
    on_turn_started/on_turn_complete/on_turn_failed 以每次物理 Provider 请求为粒度回调，
    供审计把成功、断流、空工具回复分别落库，绝不合并跨请求的计时或 token。
    """
    from src.config import settings

    total_attempts = total_attempts if total_attempts is not None else settings.models.annotation.total_attempts

    hint_resolved = False

    def _apply_completion_hint() -> None:
        """2026-09-08 首次无工具回复时向重发请求注入一次提示（原地追加调用方副本）"""
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
    while True:
        attempt += 1
        started_ns = perf_counter_ns()
        if on_turn_started is not None:
            on_turn_started(_provider_request_metadata(model, attempt=attempt), started_ns)
        aggregator = StreamChunkAggregator(
            stream,
            started_ns=started_ns,
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
                on_turn_failed(str(exc), aggregator.timing(), aggregator.finish())
            raise
        except Exception as exc:
            if on_turn_failed is not None:
                on_turn_failed(str(exc), aggregator.timing(), aggregator.finish())
            if retries_remaining <= 0 or not _is_transient_model_error(exc):
                logger.warning("模型输出流中断且重试耗尽: error=%s", exc)
                raise
            failed_attempt = total_attempts - retries_remaining
            retries_remaining -= 1
            logger.warning(
                "模型输出流中断，重发当前模型请求: error=%s retries_remaining=%s",
                exc,
                retries_remaining,
            )
            if stream is not None:
                await stream.thinking(f"模型输出流中断，正在重试当前请求（剩余 {retries_remaining} 次）")
            skip_output_prefix = "".join(aggregator._content_parts)
            announced_tools = set(aggregator._announced_tools)
            # 2026-08-13 P2-12 仅 429/连接类瞬态错误在重试前退避，避免压垮网关
            if _is_transient_model_error(exc):
                await asyncio.sleep(_retry_backoff_seconds(failed_attempt, exc))
            continue
        timing = aggregator.timing()
        # 2026-08-22 调用未正常结束（响应不含工具调用，含网关思考阶段静默截断产生的空回复）
        # 视同调用层故障：退避重发同一请求，耗尽后上抛交由上层失败审计收口
        # 2026-09-11 读者面 require_tool_call=False：无工具回复即上报完毕，正常返回
        if require_tool_call and not _is_call_complete(response):
            error = "模型调用未正常结束：响应未包含任何工具调用"
            if on_turn_failed is not None:
                on_turn_failed(error, timing, response)
            if retries_remaining <= 0:
                logger.warning("模型调用未正常结束且重试已耗尽")
                raise RuntimeError(f"{error}，重发后仍未恢复")
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
            await stream.tool_call_failed(name, text)
        else:
            await stream.tool_call_succeeded(name, text)


__all__ = [
    "AgentStream",
    "ModelCallTiming",
    "StreamChunkAggregator",
    "emit_tool_results",
    "run_model_call",
]
