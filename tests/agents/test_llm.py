"""真实 SDK 的离线流式请求、工具参数和连接回收"""

import json
from unittest.mock import patch

import httpx
import pytest
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionChunk

from src.agents.context_compaction import build_summary_messages
from src.agents.messages import AssistantMessage, SystemMessage, ToolMessage, UserMessage
from src.agents.model_client import build_chat_model, stream_delta
from src.agents.stream import run_model_call
from src.agents.stream_audit import _provider_request_metadata
from src.agents.tools import tool
from src.config import TaskModelConfig


def test_stream_delta_keeps_reasoning_arguments_and_usage_only_tail():
    chunk = ChatCompletionChunk.model_validate(
        {
            "id": "request",
            "created": 0,
            "model": "model",
            "object": "chat.completion.chunk",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": None,
                    "delta": {
                        "content": "正文",
                        "reasoning_content": "思考",
                        "tool_calls": [
                            {
                                "index": 1,
                                "id": "call",
                                "type": "function",
                                "function": {"name": "execute_code", "arguments": '{"code":'},
                            }
                        ],
                    },
                }
            ],
        }
    )
    delta = stream_delta(chunk)
    assert delta.content == "正文" and delta.additional_kwargs["reasoning_content"] == "思考"
    assert delta.tool_call_chunks == [{"index": 1, "id": "call", "name": "execute_code", "args": '{"code":'}]
    tail = chunk.model_copy(update={"choices": [], "usage": None})
    assert stream_delta(tail).tool_call_chunks == []


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
async def test_sdk_stream_serializes_history_and_accounts_usage_without_network(effort):
    requests = []
    frames = [
        {"content": "正文", "reasoning_content": "思考"},
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "new-call",
                    "type": "function",
                    "function": {"name": "execute_code", "arguments": '{"code":'},
                }
            ]
        },
        {"tool_calls": [{"index": 0, "function": {"arguments": '"finish()"}'}}]},
    ]

    def respond(request):
        requests.append(json.loads(request.content))
        events = [
            {
                "id": "request",
                "created": 0,
                "model": "model",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "finish_reason": None, "delta": delta}],
            }
            for delta in frames
        ]
        events.append(
            {
                "id": "request",
                "created": 0,
                "model": "model",
                "object": "chat.completion.chunk",
                "choices": [],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 10,
                    "total_tokens": 30,
                    "completion_tokens_details": {"reasoning_tokens": 4},
                    "prompt_tokens_details": {"cached_tokens": 3},
                },
            }
        )
        payload = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=payload)

    @tool
    def execute_code(code: str) -> str:
        """执行程序"""
        return code

    async with AsyncOpenAI(
        api_key="offline-test",
        base_url="https://model.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as client:
        with patch("src.agents.model_client.AsyncOpenAI", return_value=client) as factory:
            model = build_chat_model(
                config=TaskModelConfig(
                    model="model",
                    base_url="https://model.test/v1",
                    api_key="offline-test",
                    reasoning_effort=effort,
                    max_tokens=5000,
                )
            )
        factory.assert_called_once_with(
            base_url="https://model.test/v1",
            api_key="offline-test",
            timeout=180.0,
            max_retries=0,
        )
        bound = model.bind_tools([execute_code])
        assert not model.tools and bound.client is model.client
        result = await run_model_call(
            bound,
            [
                SystemMessage(content="系统"),
                UserMessage(content="任务"),
                AssistantMessage(
                    content="",
                    additional_kwargs={"reasoning_content": "不回传"},
                    tool_calls=[
                        {"id": "old-call", "name": "execute_code", "args": {"code": "x = None"}},
                    ],
                ),
                ToolMessage(content="回执", tool_call_id="old-call"),
            ],
            None,
            total_attempts=1,
        )
        summary_messages = build_summary_messages(
            [SystemMessage(content="系统"), UserMessage(content="任务")],
            previous_summary=None,
            shadowed=[AssistantMessage(content="需要压缩的历史")],
        )
        await run_model_call(model, summary_messages, None, require_tool_call=False, total_attempts=1)
    body = requests[0]
    assert body["stream"] and body["stream_options"] == {"include_usage": True}
    assert body["reasoning_effort"] == effort and body["max_completion_tokens"] == 5000
    assert "think" not in body and "extra_body" not in body
    assert _provider_request_metadata(bound, attempt=1)["parameters"]["reasoning_effort"] == body["reasoning_effort"]
    assert requests[1]["reasoning_effort"] == effort and "tools" not in requests[1]
    assert body["tools"][0]["function"]["name"] == "execute_code"
    assert [message["role"] for message in body["messages"]] == ["system", "user", "assistant", "tool"]
    assert "reasoning_content" not in body["messages"][2]
    assert body["messages"][3]["tool_call_id"] == "old-call"
    assert result.tool_calls[0]["args"] == {"code": "finish()"}
    assert result.additional_kwargs["reasoning_content"] == "思考"
    assert result.usage_metadata["total_tokens"] == 30
