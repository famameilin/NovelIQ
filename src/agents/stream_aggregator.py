"""
创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分 src/agents/stream.py（chunk 纯函数与流式聚合段）
说明: 承接自 stream.py 的 extract_reasoning_content、用量累加、工具调用
      增量合并与 StreamChunkAggregator；经 stream.py re-export（导入方
      零改动）。计时器经 stream 模块延迟解析以保持 monkeypatch 语义不变。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from langchain_core.messages import AIMessage, ToolCall, UsageMetadata

from src.agents.stream_audit import ModelCallTiming

if TYPE_CHECKING:
    from src.agents.stream import AgentStream

logger = logging.getLogger(__name__)


def _now_ns() -> int:
    """2026-10-02 用于经 stream 模块延迟解析计时器：拆分后仍保持对
    monkeypatch(src.agents.stream.perf_counter_ns) 的实时解析语义不变"""
    from src.agents.stream import perf_counter_ns

    return perf_counter_ns()


def extract_reasoning_content(chunk: Any) -> str:
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
        self._started_ns = started_ns if started_ns is not None else _now_ns()
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
        from src.agents.stream import StreamEmitError  # 2026-10-02 拆分：延迟导入避免与 stream.py 循环依赖

        now_ns = _now_ns()
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

        reasoning = extract_reasoning_content(chunk)
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
        now_ns = _now_ns()
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
