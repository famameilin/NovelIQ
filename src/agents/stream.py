"""
Agent 流式事件封装

将 Agent 循环中的模型推理/工具调用过程翻译为统一 StreamEvent 并发送到 SSE，
Agent 层只需持有 AgentStream 即可获得完整过程可见性。

计时说明: 流式与否由模型实例的 streaming 配置（stream_enabled）决定；
流式 Provider 得到真实 TTFT，非流式 Provider 的 TTFT 与推理时间记录为 NULL，
不会用总耗时冒充。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import AIMessage, ToolCall, UsageMetadata

from src.api.models.events import StreamEvent, StreamEventAction

_MAX_TOOL_SUMMARY_CHARS = 200

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


def _is_transient_model_error(exc: BaseException) -> bool:
    """2026-08-13 P2-6 用于判定网络/限流类瞬态错误：仅这类错误值得重发模型请求

    覆盖内置 ConnectionError/TimeoutError 以及 openai/httpx 异常类型
    （APIConnectionError/APITimeoutError/RateLimitError/ConnectError/ReadTimeout 等）。
    """
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    name = type(exc).__name__.lower()
    return any(marker in name for marker in _TRANSIENT_ERROR_MARKERS)


def _retry_backoff_seconds(attempt: int) -> float:
    """2026-08-13 P2-12 用于计算重试前退避时长：0.5s × 2^attempt 指数退避，上限 3s

    attempt 从 1 起计（第一次重试前等待 1s，第二次 2s，第三次 3s 封顶）。
    仅对 429/连接类瞬态错误生效，其余错误不额外等待。
    """
    return min(0.5 * (2 ** max(attempt, 1)), 3.0)


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


@dataclass(frozen=True, slots=True)
class ModelCallTiming:
    """2026-08-10 用于保存单次模型调用的逐项计时（毫秒）与计时口径备注"""

    ttft_ms: int | None = None
    first_visible_ms: int | None = None
    reasoning_ms: int | None = None
    model_ms: int | None = None
    timing_notes: tuple[str, ...] = ()


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
        chunk_id: int = 0,
        sub_stage: str = "",
        stream_id: str | None = None,
    ) -> None:
        self._emitter = emitter
        self._chunk_id = chunk_id
        self._sub_stage = sub_stage
        self._stream_id = stream_id or f"{sub_stage or 'agent'}-{chunk_id}"

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
                chapter_id=self._chunk_id,
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
                chapter_id=self._chunk_id,
                sub_stage=self._sub_stage,
                stream_id=self._stream_id,
            )
        )


def _extract_reasoning_token(chunk: Any) -> str:
    """
    从流式 chunk 探测推理 token（Qwen 系 reasoning_content 字段）

    不同 langchain-openai 版本对额外字段的暴露位置不同，依次探测
    additional_kwargs / response_metadata / 直接属性
    """
    additional = getattr(chunk, "additional_kwargs", None) or {}
    reasoning = additional.get("reasoning_content") or additional.get("reasoning") or ""
    if reasoning:
        return str(reasoning)

    metadata = getattr(chunk, "response_metadata", None) or {}
    reasoning = metadata.get("reasoning_content") or metadata.get("reasoning") or ""
    if reasoning:
        return str(reasoning)

    direct = getattr(chunk, "reasoning_content", None)
    if direct:
        return str(direct)
    return ""


def _accumulate_usage_metadata(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    """
    2026-08-10 用于累加流式 chunk 的用量数值字段，嵌套字典递归合并

    OpenAI 兼容网关通常在末个 chunk 返回完整 usage；部分网关按 chunk 增量上报，
    数值字段直接相加可兼容两种情况
    """
    for key, value in source.items():
        if isinstance(value, Mapping):
            nested = target.setdefault(key, {})
            _accumulate_usage_metadata(nested, value)
        elif isinstance(value, int | float) and not isinstance(value, bool):
            target[key] = target.get(key, 0) + value
        else:
            target[key] = value


def _merge_tool_call_chunks(tool_call_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    按 index 合并 langchain 流式工具调用增量，还原完整 tool_calls

    OpenAI 兼容流式接口把工具调用拆成多个分片：name 首片完整、args 为 JSON 片段增量，
    需要按 index 拼接后再解析。JSON 解析失败说明流被截断（Provider 丢尾包/模型截断），
    不再静默包装 {"_raw": ...} 执行，而是打 truncated 标记并保留原文供诊断与拒绝执行。
    2026-08-22 修复：部分网关（muse-spark via zen）并发工具返回 index 均为 0，
    需按 name/id 冲突自动分配新 index，避免名串接成单条（如 get_a+get_b）。
    """
    merged: dict[int, dict[str, str]] = {}
    for raw in tool_call_chunks:
        index = int(raw.get("index", len(merged)))
        # 若 index 已被不同 name 占用，分配新 index
        raw_name = raw.get("name") or ""
        if index in merged and raw_name and merged[index]["name"] and merged[index]["name"] != raw_name:
            index = max(merged.keys()) + 1
            # 同时检查新 index 是否仍冲突（极端情况）
            while index in merged and merged[index]["name"] and merged[index]["name"] != raw_name:
                index += 1
        entry = merged.setdefault(index, {"name": "", "args": "", "id": ""})
        name = raw_name
        if name:
            entry["name"] += name
        args = raw.get("args") or ""
        if args:
            entry["args"] += args
        call_id = raw.get("id") or ""
        if call_id:
            entry["id"] += call_id

    calls: list[dict[str, Any]] = []
    for index in sorted(merged):
        entry = merged[index]
        if not entry["name"]:
            continue
        raw_args = entry["args"]
        try:
            parsed_args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            logger.warning(
                "工具调用参数 JSON 截断（流未完整收尾）: name=%s args=%r",
                entry["name"],
                entry["args"],
            )
            calls.append(
                {
                    "name": entry["name"],
                    "args": {},
                    "raw_args": raw_args,
                    "id": entry["id"] or f"call_{index}",
                    "type": "tool_call",
                    "truncated": True,
                    "truncated_args": raw_args,
                }
            )
            continue
        calls.append(
            {
                "name": entry["name"],
                "args": parsed_args,
                "raw_args": raw_args,
                "id": entry["id"] or f"call_{index}",
                "type": "tool_call",
            }
        )
    return calls


class StreamChunkAggregator:
    """
    聚合 astream 的 AIMessageChunk，边聚合边推送事件并采集逐项计时

    文本 token → llm_output（output 块）
    工具名完整出现 → "正在调用工具 X"（tool_call 事件）
    推理 token 只聚合不推送（思考块内容由工具调用体现）
    """

    def __init__(
        self,
        stream: AgentStream | None,
        *,
        started_ns: int | None = None,
        skip_output_prefix: str = "",
        announced_tools: set[str] | None = None,
    ) -> None:
        self._stream = stream
        self._started_ns = started_ns if started_ns is not None else perf_counter_ns()
        self._content_parts: list[str] = []
        self._reasoning_parts: list[str] = []
        self._tool_call_chunks: list[dict[str, Any]] = []
        # 2026-08-13 P2-8 按工具名记录已推送 started 事件（原按 index 记录会导致
        # 断流重试后 index 相同但工具名不同时客户端看不到 started 事件）
        self._announced_tools: set[str] = set(announced_tools or ())
        self._skip_output_prefix = skip_output_prefix
        self._usage_metadata: dict[str, Any] = {}
        self._finish_reason: str | None = None
        self._ttft_ns: int | None = None
        self._first_visible_ns: int | None = None
        self._first_reasoning_ns: int | None = None
        self._last_reasoning_ns: int | None = None

    @staticmethod
    def _split_overlap(content: str, skip_prefix: str) -> tuple[str, str, str]:
        """2026-08-13 拆分与上次已推送内容的重叠部分，返回（重叠部分, 非重叠部分, 剩余跳过前缀）

        断流重试时客户端已看到失败尝试推送的全文。重叠部分进入消息链（重试
        输出的完整内容必须保留，否则后续回合上下文缺失）但不推 SSE；非重叠
        部分正常推送。重试输出整体是失败输出的前缀（非确定性 LLM 输出更短）
        时，全部落入重叠区，消息链仍保留全文，仅 SSE 不重复推送。
        """
        if not skip_prefix:
            return "", content, ""
        common = 0
        max_common = min(len(content), len(skip_prefix))
        while common < max_common and content[common] == skip_prefix[common]:
            common += 1
        if common == len(content):
            # 整个 chunk 是已推送内容的前缀：保留跳过前缀供后续 chunk 继续比对
            return content, "", skip_prefix
        return content[:common], content[common:], ""

    async def add_chunk(self, chunk: Any) -> None:
        """处理单个流式 chunk：提取并推送文本/工具调用增量，累积用量与计时"""
        now_ns = perf_counter_ns()
        content = getattr(chunk, "content", "")
        if isinstance(content, str) and content:
            # 断流重试后跳过与上次已推送部分重叠的前缀，避免客户端看到重复输出。
            # 重叠部分进消息链（保留重试输出全文）但不推 SSE，非重叠部分正常推送。
            overlap, content, self._skip_output_prefix = self._split_overlap(content, self._skip_output_prefix)
            if overlap:
                self._content_parts.append(overlap)
            if content:
                self._content_parts.append(content)
                if self._stream is not None:
                    try:
                        await self._stream.output(content)
                    except Exception as exc:
                        raise StreamEmitError(f"SSE 推送输出失败: {exc}") from exc

        reasoning = _extract_reasoning_token(chunk)
        if reasoning:
            self._reasoning_parts.append(reasoning)

        raw_tool_chunks = getattr(chunk, "tool_call_chunks", None) or []
        announced_name: str | None = None
        for raw in raw_tool_chunks:
            name = raw.get("name") or ""
            if name and name not in self._announced_tools:
                self._announced_tools.add(name)
                announced_name = name
                if self._stream is not None:
                    try:
                        await self._stream.tool_call_started(name)
                    except Exception as exc:
                        raise StreamEmitError(f"SSE 推送工具调用失败: {exc}") from exc
        if raw_tool_chunks:
            self._tool_call_chunks.extend(raw_tool_chunks)

        has_payload = bool(content) or bool(reasoning) or bool(raw_tool_chunks)
        if has_payload and self._ttft_ns is None:
            self._ttft_ns = now_ns
        if content and self._first_visible_ns is None:
            self._first_visible_ns = now_ns
        if announced_name and self._first_visible_ns is None:
            self._first_visible_ns = now_ns
        if reasoning:
            if self._first_reasoning_ns is None:
                self._first_reasoning_ns = now_ns
            self._last_reasoning_ns = now_ns

        usage_metadata = getattr(chunk, "usage_metadata", None)
        if isinstance(usage_metadata, Mapping):
            # 2026-08-13 P1-3 防御：同一 chunk 可能同时携带 LangChain 标准
            # usage_metadata 与 provider 原始 usage（response_metadata/
            # additional_kwargs），双源累加会把用量翻倍。以标准字段为准，
            # 原始字段仅作为标准字段缺失时的回退（真实网关每 turn 恰好 1 条）。
            has_usage_metadata = True
            _accumulate_usage_metadata(self._usage_metadata, usage_metadata)
        else:
            has_usage_metadata = False
        raw_usage = None
        response_metadata = getattr(chunk, "response_metadata", None)
        if isinstance(response_metadata, Mapping):
            raw_usage = response_metadata.get("token_usage") or response_metadata.get("usage")
            # 真实 Provider 实测 finish_reason 出现在倒数第二个 chunk，
            # 必须扫描全部 chunk 并保留最后一次出现的值
            finish_reason = response_metadata.get("finish_reason")
            if finish_reason:
                self._finish_reason = str(finish_reason)
        additional_kwargs = getattr(chunk, "additional_kwargs", None)
        if raw_usage is None and isinstance(additional_kwargs, Mapping):
            raw_usage = additional_kwargs.get("usage") or additional_kwargs.get("token_usage")
        if not has_usage_metadata and isinstance(raw_usage, Mapping):
            _accumulate_usage_metadata(self._usage_metadata, raw_usage)

    def finish(self) -> AIMessage:
        """合并所有分片，构造与 ainvoke 等价的完整 AIMessage"""
        content = "".join(self._content_parts)
        reasoning = "".join(self._reasoning_parts)
        tool_calls = _merge_tool_call_chunks(self._tool_call_chunks)
        message = AIMessage(content=content)
        if self._usage_metadata:
            message.usage_metadata = cast(UsageMetadata, self._usage_metadata)
        if tool_calls:
            message.tool_calls = cast(list[ToolCall], tool_calls)
        if reasoning:
            message.additional_kwargs["reasoning_content"] = reasoning
        if self._finish_reason is not None:
            message.additional_kwargs["finish_reason"] = self._finish_reason
        return message

    def timing(self) -> ModelCallTiming:
        """2026-08-10 用于按采集时间戳计算逐项耗时（毫秒）并记录计时口径备注"""
        now_ns = perf_counter_ns()
        reasoning_ms = None
        if self._first_reasoning_ns is not None and self._last_reasoning_ns is not None:
            reasoning_ms = round((self._last_reasoning_ns - self._first_reasoning_ns) / 1_000_000)
        notes: list[str] = []
        if self._ttft_ns is None:
            notes.append("provider_stream_no_payload")
        elif reasoning_ms is None:
            notes.append("reasoning_not_streamed")
        return ModelCallTiming(
            ttft_ms=(round((self._ttft_ns - self._started_ns) / 1_000_000) if self._ttft_ns is not None else None),
            first_visible_ms=(
                round((self._first_visible_ns - self._started_ns) / 1_000_000)
                if self._first_visible_ns is not None
                else None
            ),
            reasoning_ms=reasoning_ms,
            model_ms=round((now_ns - self._started_ns) / 1_000_000),
            timing_notes=tuple(notes),
        )


async def emit_completed_model_call(stream: AgentStream, response: Any) -> None:
    """
    非流式调用完成后补发文本/工具调用状态事件

    保证降级路径（模型不支持 astream）仍有过程可见性
    """
    content = getattr(response, "content", "") or ""
    if isinstance(content, str) and content:
        await stream.output(content)
    tool_calls = getattr(response, "tool_calls", None) or []
    for call in tool_calls:
        await stream.tool_call_started(str(call.get("name") or "unknown"))


async def run_model_call(
    model: Any,
    messages: list[Any],
    stream: AgentStream | None,
    *,
    on_turn_complete: Callable[[AIMessage, ModelCallTiming], None] | None = None,
    total_attempts: int | None = None,
) -> AIMessage:
    """
    调用模型并返回完整 AIMessage

    是否走流式由模型实例的 streaming 配置决定（ChatOpenAI(streaming=...)）：
    开启时用 astream 聚合分片并推送事件；关闭或 Provider 不支持流式时
    直接 ainvoke 单次调用，TTFT 与推理时间记录为 NULL。
    流式输出中途断流（astream 抛异常）时用同一 messages 重发当前模型请求，
    total_attempts 表示总调用次数（重试次数 = total_attempts - 1），
    total_attempts=1 时关闭重试；缺省对齐 settings.models.annotation.total_attempts
    （默认 3 次，即最多重试 2 次）；
    重试期间推送 thinking 事件，并跳过与上次已推送内容重叠的前缀，避免重复输出；
    已失败尝试的用量（如有）与最终用量合并记账，避免重试丢弃已消耗的 token。
    耗尽后抛出最后一次异常。SSE 推送失败（StreamEmitError）不触发重试。
    非流式路径同样遵守 total_attempts 重试语义，但只对网络/限流等瞬态错误
    （_is_transient_model_error）重发请求，其余错误直接失败。
    2026-08-22 把"响应不含任何工具调用"视同调用未正常结束（涵盖网关思考阶段
    静默截断产生的空回复），与瞬态错误共用 total_attempts 预算退避重发；
    耗尽后上抛 RuntimeError。回合审计回调先于该判定执行，截断回合仍留痕。
    on_turn_complete 在模型流结束后回调（消息 + 逐项计时），供审计落库。
    """
    from src.config import settings

    started_ns = perf_counter_ns()
    total_attempts = total_attempts if total_attempts is not None else settings.models.annotation.total_attempts
    if not hasattr(model, "astream") or not bool(getattr(model, "streaming", True)):
        retries_remaining = max(0, total_attempts - 1)
        if stream is not None:
            hint = (
                "模型不支持流式输出，等待完整回复..."
                if not hasattr(model, "astream")
                else "模型未启用流式输出，等待完整回复..."
            )
            await stream.thinking(hint)
        while True:
            try:
                response = await model.ainvoke(messages)
            except StreamEmitError:
                # 客户端已断开，重试推送也发不出去，直接上抛不再重发模型请求
                raise
            except Exception as exc:
                # 2026-08-13 P2-6 非流式路径只对网络/限流瞬态错误重试，
                # 参数/鉴权等确定性错误重试无意义
                if retries_remaining <= 0 or not _is_transient_model_error(exc):
                    raise
                failed_attempt = total_attempts - retries_remaining
                retries_remaining -= 1
                logger.warning(
                    "模型调用失败，重发当前模型请求: error=%s retries_remaining=%s",
                    exc,
                    retries_remaining,
                )
                if stream is not None:
                    await stream.thinking(f"模型调用失败，正在重试当前请求（剩余 {retries_remaining} 次）")
                await asyncio.sleep(_retry_backoff_seconds(failed_attempt))
                continue
            timing = ModelCallTiming(
                model_ms=round((perf_counter_ns() - started_ns) / 1_000_000),
                timing_notes=("provider_non_streaming",),
            )
            if stream is not None:
                await emit_completed_model_call(stream, response)
            if on_turn_complete is not None:
                on_turn_complete(response, timing)
            # 2026-08-22 调用未正常结束（响应不含工具调用）视同调用层故障：
            # 与瞬态错误共用 total_attempts 预算退避重发，耗尽后上抛
            if not _is_call_complete(response):
                if retries_remaining <= 0:
                    logger.warning("模型调用未正常结束且重试已耗尽")
                    raise RuntimeError("模型调用未正常结束：响应未包含任何工具调用，重发后仍未恢复")
                failed_attempt = total_attempts - retries_remaining
                retries_remaining -= 1
                logger.warning(
                    "模型调用未正常结束（响应不含工具调用），重发当前模型请求: retries_remaining=%s",
                    retries_remaining,
                )
                if stream is not None:
                    await stream.thinking(f"模型调用未正常结束，正在重试当前请求（剩余 {retries_remaining} 次）")
                await asyncio.sleep(_retry_backoff_seconds(failed_attempt))
                continue
            return response

    retries_remaining = max(0, total_attempts - 1)
    skip_output_prefix = ""
    announced_tools: set[str] = set()
    retried_usage: dict[str, Any] = {}
    while True:
        aggregator = StreamChunkAggregator(
            stream,
            started_ns=started_ns,
            skip_output_prefix=skip_output_prefix,
            announced_tools=announced_tools,
        )
        try:
            async for chunk in model.astream(messages):
                await aggregator.add_chunk(chunk)
        except StreamEmitError:
            # 客户端已断开，重试推送也发不出去，直接上抛不再重发模型请求
            raise
        except Exception as exc:
            if retries_remaining <= 0:
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
            if aggregator._usage_metadata:
                _accumulate_usage_metadata(retried_usage, aggregator._usage_metadata)
            skip_output_prefix = "".join(aggregator._content_parts)
            announced_tools = set(aggregator._announced_tools)
            # 2026-08-13 P2-12 仅 429/连接类瞬态错误在重试前退避，避免压垮网关
            if _is_transient_model_error(exc):
                await asyncio.sleep(_retry_backoff_seconds(failed_attempt))
            continue
        response = aggregator.finish()
        if retried_usage:
            # 已失败尝试的用量与最终成功尝试的用量合并，避免断流重试丢弃已消耗 token
            _accumulate_usage_metadata(retried_usage, dict(response.usage_metadata or {}))
            response.usage_metadata = cast(UsageMetadata, retried_usage)
        if on_turn_complete is not None:
            on_turn_complete(response, aggregator.timing())
        # 2026-08-22 调用未正常结束（响应不含工具调用，含网关思考阶段静默截断产生的空回复）
        # 视同调用层故障：退避重发同一请求，耗尽后上抛交由上层失败审计收口
        if not _is_call_complete(response):
            if retries_remaining <= 0:
                logger.warning("模型调用未正常结束且重试已耗尽")
                raise RuntimeError("模型调用未正常结束：响应未包含任何工具调用，重发后仍未恢复")
            failed_attempt = total_attempts - retries_remaining
            retries_remaining -= 1
            logger.warning(
                "模型调用未正常结束（响应不含工具调用），重发当前模型请求: retries_remaining=%s",
                retries_remaining,
            )
            if aggregator._usage_metadata:
                _accumulate_usage_metadata(retried_usage, aggregator._usage_metadata)
            skip_output_prefix = "".join(aggregator._content_parts)
            announced_tools = set(aggregator._announced_tools)
            if stream is not None:
                await stream.thinking(f"模型调用未正常结束，正在重试当前请求（剩余 {retries_remaining} 次）")
            await asyncio.sleep(_retry_backoff_seconds(failed_attempt))
            continue
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
    "emit_completed_model_call",
    "emit_tool_results",
    "run_model_call",
]
