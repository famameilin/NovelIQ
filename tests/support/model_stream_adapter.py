"""StreamedFakeModelMixin：给只实现 ainvoke 的测试假模型补上等价 astream 接口

创建时间: 2026-10-02
创建者: TraeWork
任务: 删除 LLM 非流式兜底（src/agents/stream.py 的 run_model_call 统一走
astream 流式聚合）后的测试适配
说明: run_model_call 不再回退 ainvoke，ainvoke-only 假模型会直接
AttributeError。测试模型继承本混入后，astream 调用宿主类自身的 ainvoke
取得完整 AIMessage，并包装成单 chunk 的 AIMessageChunk 流
（tool_calls 还原为 tool_call_chunks、usage_metadata 原样透传），
StreamChunkAggregator 聚合结果与 ainvoke 返回等价。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessageChunk


class StreamedFakeModelMixin:
    """把 ainvoke 的完整返回包装成单 chunk astream 的测试混入（宿主类需实现 ainvoke）"""

    streaming = True

    async def astream(self, messages: list[Any]):
        response = await self.ainvoke(messages)
        tool_call_chunks = [
            {
                "name": str(call.get("name") or ""),
                "args": json.dumps(call.get("args") or {}, ensure_ascii=False),
                "id": str(call.get("id") or f"call_{index}"),
                "index": index,
            }
            for index, call in enumerate(getattr(response, "tool_calls", None) or [])
        ]
        yield AIMessageChunk(
            content=response.content if isinstance(response.content, str) else "",
            tool_call_chunks=tool_call_chunks,
            usage_metadata=getattr(response, "usage_metadata", None),
        )
