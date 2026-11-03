"""OpenAI 兼容模型的流式请求与响应适配"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from openai import AsyncOpenAI

from src.config import TaskModelConfig, TaskType
from src.config.input_config import DEFAULT_REASONING_EFFORT, ReasoningEffort
from src.model_pool.configuration import load_task_config


class ModelMessage(Protocol):
    """请求侧提供的供应商消息序列化入口"""

    def provider_message(self) -> dict[str, Any]: ...


class ModelTool(Protocol):
    """请求侧提供的工具 schema 入口"""

    def provider_schema(self) -> dict[str, Any]: ...


@dataclass(kw_only=True)
class StreamDelta:
    """一次供应商流式响应的正文、参数分片与计量增量"""

    content: str | list[Any] = ""
    tool_call_chunks: list[dict[str, Any]] = field(default_factory=list)
    additional_kwargs: dict[str, Any] = field(default_factory=dict)
    response_metadata: dict[str, Any] = field(default_factory=dict)
    usage_metadata: dict[str, Any] | None = None


def stream_delta(chunk: Any) -> StreamDelta:
    """保留供应商原始用量、思考字段和按索引分片的调用参数"""
    usage = chunk.usage.model_dump(exclude_none=True) if chunk.usage is not None else None
    result = StreamDelta(usage_metadata=usage)
    if not chunk.choices:
        return result
    choice = chunk.choices[0]
    delta = choice.delta
    result.content = delta.content or ""
    reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
    if reasoning:
        result.additional_kwargs["reasoning_content"] = reasoning
    if choice.finish_reason is not None:
        result.response_metadata["finish_reason"] = choice.finish_reason
    for call in delta.tool_calls or []:
        function = call.function
        result.tool_call_chunks.append(
            {
                "index": call.index,
                "id": call.id,
                "name": function.name if function is not None else None,
                "args": function.arguments if function is not None else None,
            }
        )
    return result


@dataclass
class OpenAIChatModel:
    """模型池配置对应的流式客户端，绑定工具时复用连接"""

    client: AsyncOpenAI
    model: str
    base_url: str | None
    temperature: float | None
    top_p: float | None
    max_completion_tokens: int | None
    timeout_s: float
    reasoning_effort: ReasoningEffort = DEFAULT_REASONING_EFFORT
    tools: list[dict[str, Any]] = field(default_factory=list)

    def bind_tools(self, tools: Sequence[ModelTool]) -> OpenAIChatModel:
        """生成独立工具绑定，不改变摘要请求使用的无工具客户端"""
        return replace(self, tools=[candidate.provider_schema() for candidate in tools])

    async def astream(self, messages: Sequence[ModelMessage]) -> AsyncIterator[StreamDelta]:
        """流结束、异常或取消时关闭响应连接"""
        parameters: dict[str, Any] = {
            "model": self.model,
            "messages": [message.provider_message() for message in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
            "reasoning_effort": self.reasoning_effort,
        }
        if self.max_completion_tokens is not None:
            parameters["max_completion_tokens"] = self.max_completion_tokens
        if self.temperature is not None:
            parameters["temperature"] = self.temperature
        if self.top_p is not None:
            parameters["top_p"] = self.top_p
        if self.tools:
            parameters["tools"] = self.tools
        response = await self.client.chat.completions.create(**parameters)
        try:
            async for chunk in response:
                yield stream_delta(chunk)
        finally:
            await response.close()


def build_chat_model(
    task_type: TaskType = "annotation",
    config: TaskModelConfig | None = None,
) -> OpenAIChatModel:
    """使用项目任务配置构建客户端，请求重试由 Agent 请求层统一负责"""
    cfg = config or load_task_config(task_type)
    cfg.validate()
    timeout = float(cfg.timeout_s if cfg.timeout_s is not None else 180)
    return OpenAIChatModel(
        client=AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key or None, timeout=timeout, max_retries=0),
        model=cfg.model or "",
        base_url=cfg.base_url,
        temperature=cfg.temperature,
        top_p=cfg.top_p,
        max_completion_tokens=cfg.max_tokens,
        timeout_s=timeout,
        reasoning_effort=cfg.reasoning_effort,
    )
