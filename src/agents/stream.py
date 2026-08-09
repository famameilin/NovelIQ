"""
Agent 流式事件封装

将 Agent 循环中的模型推理/工具调用过程翻译为统一 StreamEvent 并发送到 SSE，
Agent 层只需持有 AgentStream 即可获得完整过程可见性。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

from langchain_core.messages import AIMessage, ToolCall

from src.api.models.events import StreamEvent, StreamEventAction

_MAX_TOOL_SUMMARY_CHARS = 200


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
        chunk_id: int = 0,
        sub_stage: str = "",
    ) -> None:
        self._emitter = emitter
        self._chunk_id = chunk_id
        self._sub_stage = sub_stage

    async def thinking(self, text: str) -> None:
        """发送思考/推理过程事件"""
        await self._emit("thinking", text)

    async def output(self, text: str) -> None:
        """发送模型正式输出事件"""
        await self._emit("output", text)

    async def tool_call_started(self, name: str, args_summary: str = "") -> None:
        """发送工具调用开始事件"""
        text = f"正在调用工具 {name}"
        if args_summary:
            text = f"{text}：{args_summary}"
        await self._emit("thinking", text)

    async def tool_call_succeeded(self, name: str, summary: str = "") -> None:
        """发送工具执行成功事件"""
        text = f"工具 {name} 执行成功"
        if summary:
            text = f"{text}：{_truncate(summary)}"
        await self._emit("thinking", text)

    async def tool_call_failed(self, name: str, error: str = "") -> None:
        """发送工具执行失败事件"""
        text = f"工具 {name} 执行失败"
        if error:
            text = f"{text}：{_truncate(error)}"
        await self._emit("thinking", text)

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


def _merge_tool_call_chunks(tool_call_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    按 index 合并 langchain 流式工具调用增量，还原完整 tool_calls

    OpenAI 兼容流式接口把工具调用拆成多个分片：name 首片完整、args 为 JSON 片段增量，
    需要按 index 拼接后再解析
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
        try:
            parsed_args = json.loads(entry["args"]) if entry["args"] else {}
        except json.JSONDecodeError:
            parsed_args = {"_raw": entry["args"]}
        calls.append(
            {
                "name": entry["name"],
                "args": parsed_args,
                "id": entry["id"] or f"call_{index}",
                "type": "tool_call",
            }
        )
    return calls


class StreamChunkAggregator:
    """
    聚合 astream 的 AIMessageChunk，边聚合边推送事件

    文本 token → llm_output（output tab）
    reasoning token → llm_thinking（thinking tab）
    工具名完整出现 → "正在调用工具 X"（thinking tab）
    """

    def __init__(self, stream: AgentStream) -> None:
        self._stream = stream
        self._content_parts: list[str] = []
        self._reasoning_parts: list[str] = []
        self._tool_call_chunks: list[dict[str, Any]] = []
        self._announced_tools: set[int] = set()

    async def add_chunk(self, chunk: Any) -> None:
        """处理单个流式 chunk：提取并推送文本/推理/工具调用增量"""
        content = getattr(chunk, "content", "")
        if isinstance(content, str) and content:
            self._content_parts.append(content)
            await self._stream.output(content)

        reasoning = _extract_reasoning_token(chunk)
        if reasoning:
            self._reasoning_parts.append(reasoning)
            await self._stream.thinking(reasoning)

        raw_tool_chunks = getattr(chunk, "tool_call_chunks", None) or []
        for raw in raw_tool_chunks:
            index = int(raw.get("index", len(self._tool_call_chunks)))
            name = raw.get("name") or ""
            if name and index not in self._announced_tools:
                self._announced_tools.add(index)
                await self._stream.tool_call_started(name)
        if raw_tool_chunks:
            self._tool_call_chunks.extend(raw_tool_chunks)

    def finish(self) -> AIMessage:
        """合并所有分片，构造与 ainvoke 等价的完整 AIMessage"""
        content = "".join(self._content_parts)
        reasoning = "".join(self._reasoning_parts)
        tool_calls = _merge_tool_call_chunks(self._tool_call_chunks)
        message = AIMessage(content=content)
        if tool_calls:
            message.tool_calls = cast(list[ToolCall], tool_calls)
        if reasoning:
            message.additional_kwargs["reasoning_content"] = reasoning
        return message

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
) -> AIMessage:
    """
    调用模型并返回完整 AIMessage

    有 stream 且模型支持流式时逐 chunk 推送（文本/推理/工具调用），
    否则一次性 ainvoke 后补发过程状态事件
    """
    if stream is None:
        return await model.ainvoke(messages)

    if not hasattr(model, "astream"):
        await stream.thinking("模型不支持流式输出，等待完整回复...")
        response = await model.ainvoke(messages)
        await emit_completed_model_call(stream, response)
        return response

    aggregator = StreamChunkAggregator(stream)
    async for chunk in model.astream(messages):
        await aggregator.add_chunk(chunk)
    return aggregator.finish()


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
    "StreamChunkAggregator",
    "emit_completed_model_call",
    "emit_tool_results",
    "run_model_call",
]
