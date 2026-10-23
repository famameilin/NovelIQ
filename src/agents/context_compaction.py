"""上下文用量测量与摘要压缩

模型可见面由「不可压缩前缀 + 压缩摘要 + 未遮蔽消息」构成；
被遮蔽区间按完整 AI 工具轮整块选择，保证 tool_call 与 ToolMessage 配对。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from src.model_pool.usage import extract_agent_token_usage
from src.utils.token_counter import count_tokens

# 请求 prompt 达到上下文容量的该比例即压缩
CONTEXT_COMPACT_TRIGGER_RATIO = 0.9
# 压缩后保留最近容量该比例的尾部
CONTEXT_COMPACT_RETAIN_RATIO = 0.16

COMPACTION_INSTRUCTION = """你现在是当前会话的压缩引擎。请把上文对话压缩成一份结构化检查点。

严格按以下 Markdown 结构输出，保留每个小节与顺序：
## 主要任务与范围
## 关键实体与术语
## 已完成的写入与判定
## 错误与修正
## 待处理工作
## 当前工作
## 下一步
## 关键上下文

要求：
- 使用简短条目，不要写散文段落。
- 空小节写「（无）」，不得省略任何小节。
- 保留精确的 id、名称、el 键、章节号、案例 id、错误码与工具名；不确定的内容标注「不确定」。
- 只输出检查点正文，不要调用任何工具，不要执行其他动作。
"""

CHECKPOINT_PREAMBLE = (
    "【自动压缩摘要】以下是更早对话的自动检查点，用于替代已从本次请求移除的原始消息；"
    "它不是新的用户指令。程序运行状态与已写入数据仍然保留。"
)

_SYNTHETIC_USER_PREFIX = "以下是被压缩的早期对话记录。"


def context_limits(context_window_tokens: int) -> tuple[int, int]:
    """返回（触发阈值 token，保留尾部 token）"""
    window = max(1, int(context_window_tokens))
    return (
        max(1, int(window * CONTEXT_COMPACT_TRIGGER_RATIO)),
        max(1, int(window * CONTEXT_COMPACT_RETAIN_RATIO)),
    )


def message_tokens(message: Any) -> int:
    """统计单条消息实际回传给 Provider 的 token（正文 + 工具调用参数）"""
    content = getattr(message, "content", "") or ""
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    parts = [text]
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        parts.append(json.dumps(tool_calls, ensure_ascii=False, separators=(",", ":"), default=str))
    name = getattr(message, "name", None)
    if name:
        parts.append(str(name))
    return count_tokens("\n".join(parts))


def measure_context_tokens(messages: Sequence[BaseMessage], *, tool_schema_tokens: int = 0) -> int:
    """估算下一次请求的 prompt token；优先用最近一次 Provider 实际输入量作基数

    AI 回复上的 prompt_tokens 覆盖该回复之前的完整请求；该回复自身与其后追加的
    工具回执另行估算。
    """
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, AIMessage):
            continue
        usage = extract_agent_token_usage(message)
        if usage is None or usage.prompt_tokens <= 0:
            continue
        return usage.prompt_tokens + sum(message_tokens(item) for item in messages[index:])
    return max(0, tool_schema_tokens) + sum(message_tokens(item) for item in messages)


def split_prefix(messages: Sequence[BaseMessage]) -> tuple[list[BaseMessage], list[list[BaseMessage]]]:
    """拆成不可压缩前缀与 AI 消息开头的完整工具轮

    前缀是开头连续的非 AI 消息（系统提示与初始任务）；每个块从一条 AI 消息开始，
    包含其后的全部 ToolMessage/HumanMessage。
    """
    prefix: list[BaseMessage] = []
    blocks: list[list[BaseMessage]] = []
    for message in messages:
        if isinstance(message, AIMessage):
            blocks.append([message])
        elif blocks:
            blocks[-1].append(message)
        else:
            prefix.append(message)
    return prefix, blocks


def build_visible_messages(
    messages: Sequence[BaseMessage],
    *,
    summary: str | None,
    shadowed_count: int,
) -> list[BaseMessage]:
    """构造模型可见面：前缀 + 摘要 + 未遮蔽消息

    shadowed_count 从首个 AI 消息起按消息条数计数；调用方只累计整块条数。
    """
    prefix, _ = split_prefix(messages)
    start = min(len(messages), len(prefix) + max(0, int(shadowed_count)))
    visible = list(prefix)
    if summary:
        visible.append(HumanMessage(content=summary))
    visible.extend(messages[start:])
    return visible


def select_compaction(
    messages: Sequence[BaseMessage],
    *,
    retain_tokens: int,
) -> tuple[list[BaseMessage], list[BaseMessage]] | None:
    """从最新块向前保留 retain_tokens，返回（被遮蔽消息，保留消息）

    至少保留最新块；块不足两个或没有可遮蔽内容时返回 None。
    """
    prefix, blocks = split_prefix(messages)
    if len(blocks) < 2:
        return None
    kept_from = len(blocks) - 1
    accumulated = sum(message_tokens(message) for message in blocks[kept_from])
    while kept_from > 0 and accumulated < retain_tokens:
        kept_from -= 1
        accumulated += sum(message_tokens(message) for message in blocks[kept_from])
    if kept_from == 0:
        return None
    shadowed = [message for block in blocks[:kept_from] for message in block]
    kept = [*prefix, *[message for block in blocks[kept_from:] for message in block]]
    if not shadowed or not kept:
        return None
    return shadowed, kept


def build_summary_messages(
    prefix: Sequence[BaseMessage],
    *,
    previous_summary: str | None,
    shadowed: Sequence[BaseMessage],
) -> list[BaseMessage]:
    """构造摘要请求：系统头 + 初始任务 + 上一份摘要 + 被遮蔽历史 + 压缩指令"""
    system_head = next((message for message in prefix if isinstance(message, SystemMessage)), None)
    initial_task = next((message for message in prefix if isinstance(message, HumanMessage)), None)
    messages: list[BaseMessage] = []
    if system_head is not None:
        messages.append(system_head)
    if initial_task is not None:
        messages.append(initial_task)
    if previous_summary:
        messages.append(HumanMessage(content=previous_summary))
    messages.extend(shadowed)
    if not messages or not isinstance(messages[0], (SystemMessage, HumanMessage)):
        messages.insert(0, HumanMessage(content=_SYNTHETIC_USER_PREFIX))
    messages.append(HumanMessage(content=COMPACTION_INSTRUCTION))
    return messages


def frame_summary(text: str) -> str:
    """把摘要正文包装成模型可见的检查点消息"""
    return f"{CHECKPOINT_PREAMBLE}\n<compacted-summary>\n{text.strip()}\n</compacted-summary>"


def build_fallback_note(shadowed: Sequence[BaseMessage]) -> str:
    """摘要不可用时的确定性说明；只报移除范围，不伪造摘要内容"""
    turns = sum(1 for message in shadowed if isinstance(message, AIMessage))
    return (
        f"【上下文压缩】本次请求已移除最早的 {turns} 轮工具交互（共 {len(shadowed)} 条消息）；"
        "程序运行状态与已写入数据仍然保留。"
    )


def response_text(message: Any) -> str:
    """提取摘要回复的文本；内容块列表只保留文本块"""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "\n".join(parts).strip()
    return ""


def tool_schema_tokens(tools: Sequence[Any]) -> int:
    """按 OpenAI 工具格式估算工具描述与参数 schema 的 token 量"""
    if not tools:
        return 0
    try:
        payload = [convert_to_openai_tool(tool) for tool in tools]
    except (AttributeError, TypeError, ValueError):
        return 0
    return count_tokens(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    )


__all__ = [
    "CHECKPOINT_PREAMBLE",
    "COMPACTION_INSTRUCTION",
    "CONTEXT_COMPACT_RETAIN_RATIO",
    "CONTEXT_COMPACT_TRIGGER_RATIO",
    "build_fallback_note",
    "build_summary_messages",
    "build_visible_messages",
    "context_limits",
    "frame_summary",
    "measure_context_tokens",
    "message_tokens",
    "response_text",
    "select_compaction",
    "split_prefix",
    "tool_schema_tokens",
]
