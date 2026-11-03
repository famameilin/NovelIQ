"""Agent 会话消息、流式增量与调用身份合并"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, ClassVar
from uuid import uuid4


@dataclass(kw_only=True)
class Message:
    """一次会话中的消息正文和身份"""

    content: str | list[Any] = ""
    id: str | None = None
    name: str | None = None
    role: ClassVar[str]

    def provider_message(self) -> dict[str, Any]:
        """序列化正文与调用关联，计量和思考内容不进入后续提示"""
        item: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name is not None:
            item["name"] = self.name
        if isinstance(self, ToolMessage):
            item["tool_call_id"] = self.tool_call_id
        if isinstance(self, AssistantMessage) and self.tool_calls:
            item["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": call.get("raw_args")
                        if call.get("raw_args") is not None
                        else json.dumps(call.get("args", {}), ensure_ascii=False),
                    },
                }
                for call in self.tool_calls
            ]
        return item


@dataclass(kw_only=True)
class SystemMessage(Message):
    """模型系统指令"""

    role: ClassVar[str] = "system"


@dataclass(kw_only=True)
class UserMessage(Message):
    """用户任务或程序反馈"""

    role: ClassVar[str] = "user"


@dataclass(kw_only=True)
class AssistantMessage(Message):
    """完整模型响应及其工具调用和计量数据"""

    role: ClassVar[str] = "assistant"
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    additional_kwargs: dict[str, Any] = field(default_factory=dict)
    response_metadata: dict[str, Any] = field(default_factory=dict)
    usage_metadata: dict[str, Any] | None = None


@dataclass(kw_only=True)
class ToolMessage(Message):
    """与模型调用身份配对的工具回执"""

    role: ClassVar[str] = "tool"
    tool_call_id: str


def merge_messages(history: list[Message], updates: list[Message]) -> list[Message]:
    """同身份消息原位更新，其余消息按顺序追加"""
    merged = list(history)
    positions: dict[str, int] = {}
    for index, message in enumerate(merged):
        if message.id is None:
            message.id = str(uuid4())
        positions[message.id] = index
    for message in updates:
        if message.id is None:
            message.id = str(uuid4())
        if message.id in positions:
            merged[positions[message.id]] = message
        else:
            positions[message.id] = len(merged)
            merged.append(message)
    return merged
