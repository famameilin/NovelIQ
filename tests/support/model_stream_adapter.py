"""StreamedFakeModelMixin：给只实现 ainvoke 的测试假模型补上等价 astream 接口"""

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
