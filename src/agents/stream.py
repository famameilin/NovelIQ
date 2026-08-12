"""
Agent 流式事件封装

将 Agent 循环中的模型推理/工具调用过程翻译为统一 StreamEvent 并发送到 SSE，
Agent 层只需持有 AgentStream 即可获得完整过程可见性。

计时说明: 无论是否开启 SSE 都优先走 Provider 流式接口以得到真实 TTFT；
非流式 Provider 的 TTFT 与推理时间记录为 NULL，不会用总耗时冒充。
"""

from __future__ import annotations

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


class StreamEmitError(RuntimeError):
    """2026-08-12 用于区分 SSE 推送失败与模型输出流中断：推送失败不触发模型请求重试"""


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
    ) -> None:
        self._emitter = emitter
        self._chunk_id = chunk_id
        self._sub_stage = sub_stage

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
                chunk_id=self._chunk_id,
                sub_stage=self._sub_stage,
            )
        )

    async def _emit_tool(self, name: str, status: str, message: str) -> None:
        await self._emitter(
            StreamEvent(
                action="tool_call",
                content=name,
                message=message,
                status=status,
                chunk_id=self._chunk_id,
                sub_stage=self._sub_stage,
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
    """
    merged: dict[int, dict[str, str]] = {}
    for raw in tool_call_chunks:
        index = int(raw.get("index", len(merged)))
        entry = merged.setdefault(index, {"name": "", "args": "", "id": ""})
        name = raw.get("name") or ""
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
        skip_output_chars: int = 0,
        announced_tools: set[int] | None = None,
    ) -> None:
        self._stream = stream
        self._started_ns = started_ns if started_ns is not None else perf_counter_ns()
        self._content_parts: list[str] = []
        self._reasoning_parts: list[str] = []
        self._tool_call_chunks: list[dict[str, Any]] = []
        self._announced_tools: set[int] = set(announced_tools or ())
        self._skip_output_chars = max(0, skip_output_chars)
        self._usage_metadata: dict[str, Any] = {}
        self._finish_reason: str | None = None
        self._ttft_ns: int | None = None
        self._first_visible_ns: int | None = None
        self._first_reasoning_ns: int | None = None
        self._last_reasoning_ns: int | None = None

    async def add_chunk(self, chunk: Any) -> None:
        """处理单个流式 chunk：提取并推送文本/工具调用增量，累积用量与计时"""
        now_ns = perf_counter_ns()
        content = getattr(chunk, "content", "")
        if isinstance(content, str) and content:
            # 断流重试后跳过与上次已推送部分重叠的前缀，避免客户端看到重复输出
            if self._skip_output_chars > 0:
                if len(content) <= self._skip_output_chars:
                    self._skip_output_chars -= len(content)
                    content = ""
                else:
                    content = content[self._skip_output_chars :]
                    self._skip_output_chars = 0
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
            index = int(raw.get("index", len(self._tool_call_chunks)))
            name = raw.get("name") or ""
            if name and index not in self._announced_tools:
                self._announced_tools.add(index)
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
            _accumulate_usage_metadata(self._usage_metadata, usage_metadata)
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
        if isinstance(raw_usage, Mapping):
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
            ttft_ms=(
                round((self._ttft_ns - self._started_ns) / 1_000_000)
                if self._ttft_ns is not None
                else None
            ),
            first_visible_ms=(
                round((self._first_visible_ns - self._started_ns) / 1_000_000)
                if self._first_visible_ns is not None
                else None
            ),
            reasoning_ms=reasoning_ms,
            model_ms=round((now_ns - self._started_ns) / 1_000_000),
            timing_notes=tuple(notes),
        )

    def has_tool_calls(self) -> bool:
        """判断本轮流式响应是否包含工具调用"""
        return bool(self._announced_tools) or bool(self._tool_call_chunks)


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
    retries: int | None = None,
) -> AIMessage:
    """
    调用模型并返回完整 AIMessage

    无论是否开启 SSE 都优先走 Provider 流式接口，否则无法得到真实 TTFT；
    非流式 Provider 的 TTFT 与推理时间记录为 NULL，不会用总耗时冒充。
    流式输出中途断流（astream 抛异常）时用同一 messages 重发当前模型请求，
    重试次数由 retries 显式传入（由调用方按任务模型配置决定），
    缺省时对齐 settings.models.annotation.total_attempts（默认 3 次）；
    重试期间推送 thinking 事件，并跳过与上次已推送内容重叠的前缀，避免重复输出；
    耗尽后抛出最后一次异常。SSE 推送失败（StreamEmitError）不触发重试。
    on_turn_complete 在模型流结束后回调（消息 + 逐项计时），供审计落库。
    """
    started_ns = perf_counter_ns()
    if not hasattr(model, "astream"):
        if stream is not None:
            await stream.thinking("模型不支持流式输出，等待完整回复...")
        response = await model.ainvoke(messages)
        timing = ModelCallTiming(
            model_ms=round((perf_counter_ns() - started_ns) / 1_000_000),
            timing_notes=("provider_non_streaming",),
        )
        if stream is not None:
            await emit_completed_model_call(stream, response)
        if on_turn_complete is not None:
            on_turn_complete(response, timing)
        return response

    from src.config import settings

    retries_remaining = max(1, retries if retries is not None else settings.models.annotation.total_attempts)
    skip_output_chars = 0
    announced_tools: set[int] = set()
    while True:
        aggregator = StreamChunkAggregator(
            stream,
            started_ns=started_ns,
            skip_output_chars=skip_output_chars,
            announced_tools=announced_tools,
        )
        try:
            async for chunk in model.astream(messages):
                await aggregator.add_chunk(chunk)
        except StreamEmitError:
            # 客户端已断开，重试推送也发不出去，直接上抛不再重发模型请求
            raise
        except Exception as exc:  # noqa: BLE001
            if retries_remaining <= 0:
                logger.warning("模型输出流中断且重试耗尽: error=%s", exc)
                raise
            retries_remaining -= 1
            logger.warning(
                "模型输出流中断，重发当前模型请求: error=%s retries_remaining=%s",
                exc,
                retries_remaining,
            )
            if stream is not None:
                await stream.thinking(
                    f"模型输出流中断，正在重试当前请求（剩余 {retries_remaining} 次）"
                )
            skip_output_chars = len("".join(aggregator._content_parts))
            announced_tools = set(aggregator._announced_tools)
            continue
        response = aggregator.finish()
        if on_turn_complete is not None:
            on_turn_complete(response, aggregator.timing())
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
        is_failed = (
            text.startswith("Error:")
            or '"error"' in text
            or "执行失败" in text
            or "校验失败" in text
        )
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
