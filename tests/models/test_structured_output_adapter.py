"""
结构化输出适配层测试。

创建时间: 2026-04-24
任务: structured-output-adapter-instructor-unification
说明: 覆盖 json_schema / json_object 两种 mode、provider 覆盖以及失败时 raw_response 保留。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from src.config import TaskModelConfig, settings
from src.config.schemas.model import _parse_structured_output_settings
from src.models.local.base import BaseModelClient
from src.models.structured_output import (
    StructuredOutputError,
    StructuredOutputRequest,
    call_structured_output,
)


class _AdapterPayload(BaseModel):
    """
    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    说明: 适配层测试使用的最小 Pydantic 响应模型。
    """

    name: str
    score: int


def test_structured_output_settings_rejects_removed_instructor_mode() -> None:
    """
    创建时间: 2026-04-24
    任务: remove-instructor-structured-output
    说明: Instructor 已从结构化输出运行时移除，配置层也应拒绝 instructor_json。
    """
    with pytest.raises(ValueError, match="json_object"):
        _parse_structured_output_settings({"mention_extraction": "instructor_json"})


def _make_response(content: object) -> SimpleNamespace:
    """
    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    说明: 构造最小 ChatCompletion-like 响应对象，避免单测访问真实 provider。
    """
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _make_client(
    fake_create: AsyncMock,
    *,
    task_type: str = "level3_rerank",
    base_url: str = "http://127.0.0.1:8000/v1",
) -> BaseModelClient:
    """
    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    说明: 构造注入 fake SDK 的 BaseModelClient，验证适配层只组装请求不触发网络。
    """
    fake_sdk_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
    return BaseModelClient(
        task_type=task_type,  # type: ignore[arg-type]
        config=TaskModelConfig(base_url=base_url, model="test-model", api_key="test-key"),
        client=fake_sdk_client,
    )


@pytest.mark.asyncio
async def test_structured_output_json_schema_mode_uses_strict_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    说明: json_schema mode 应继续使用 BaseModelClient 的 strict schema builder。
    """
    monkeypatch.setattr(settings.structured_output, "level3_rerank", "json_schema")
    fake_create = AsyncMock(return_value=_make_response('{"name":"白芷","score":7}'))
    client = _make_client(fake_create)

    result = await call_structured_output(
        client,
        StructuredOutputRequest(
            messages=[{"role": "user", "content": "return json"}],
            response_model=_AdapterPayload,
            call_type="level3_rerank",
            enable_thinking=False,
        ),
    )

    assert result.parsed == _AdapterPayload(name="白芷", score=7)
    assert result.mode == "json_schema"
    assert fake_create.await_args.kwargs["response_format"]["type"] == "json_schema"


@pytest.mark.asyncio
async def test_structured_output_json_object_mode_uses_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    说明: json_object mode 应发送 provider 原生 JSON Output，并继续用 Pydantic 校验。
    """
    monkeypatch.setattr(settings.structured_output, "mention_extraction", "json_object")
    fake_create = AsyncMock(return_value=_make_response('{"name":"白芷","score":7}'))
    client = _make_client(fake_create, task_type="mention_extraction")

    result = await call_structured_output(
        client,
        StructuredOutputRequest(
            messages=[{"role": "user", "content": "请输出 json"}],
            response_model=_AdapterPayload,
            call_type="mention_extraction",
            enable_thinking=False,
        ),
    )

    assert result.parsed.score == 7
    assert result.mode == "json_object"
    assert fake_create.await_args.kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_structured_output_deepseek_downgrades_json_schema_to_json_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    说明: provider 能力判断集中在适配层；DeepSeek 类 provider 即使配置 json_schema 也降级为 json_object。
    """
    monkeypatch.setattr(settings.structured_output, "level3_rerank", "json_schema")
    fake_create = AsyncMock(return_value=_make_response('{"name":"白芷","score":7}'))
    client = _make_client(fake_create, base_url="https://api.deepseek.com/v1")

    result = await call_structured_output(
        client,
        StructuredOutputRequest(
            messages=[{"role": "user", "content": "请输出 json"}],
            response_model=_AdapterPayload,
            call_type="level3_rerank",
            enable_thinking=False,
        ),
    )

    assert result.mode == "json_object"
    assert fake_create.await_args.kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_structured_output_provider_override_can_force_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    说明: provider_overrides 是集中能力表；当 marker 指定 json_schema 时，应覆盖任务默认 json_object。
    """
    monkeypatch.setattr(settings.structured_output, "mention_extraction", "json_object")
    monkeypatch.setattr(settings.structured_output, "provider_overrides", {"strict-provider": "json_schema"})
    fake_create = AsyncMock(return_value=_make_response('{"name":"白芷","score":7}'))
    client = _make_client(
        fake_create,
        task_type="mention_extraction",
        base_url="https://strict-provider.example/v1",
    )

    result = await call_structured_output(
        client,
        StructuredOutputRequest(
            messages=[{"role": "user", "content": "请输出 json"}],
            response_model=_AdapterPayload,
            call_type="mention_extraction",
            enable_thinking=False,
        ),
    )

    assert result.mode == "json_schema"
    assert fake_create.await_args.kwargs["response_format"]["type"] == "json_schema"


@pytest.mark.asyncio
async def test_structured_output_empty_content_raises_with_raw_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    说明: provider 返回空 content 时必须显式抛错，并把 raw_response 带给调用方补账。
    """
    monkeypatch.setattr(settings.structured_output, "level3_rerank", "json_schema")
    raw_response = _make_response("")
    fake_create = AsyncMock(return_value=raw_response)
    client = _make_client(fake_create)

    with pytest.raises(StructuredOutputError, match="Empty content") as exc_info:
        await call_structured_output(
            client,
            StructuredOutputRequest(
                messages=[{"role": "user", "content": "return json"}],
                response_model=_AdapterPayload,
                call_type="level3_rerank",
                enable_thinking=False,
            ),
        )

    assert exc_info.value.raw_response is raw_response


@pytest.mark.asyncio
async def test_structured_output_invalid_json_raises_with_response_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    说明: 非法 JSON 不能被静默忽略，错误对象应保留 response_text。
    """
    monkeypatch.setattr(settings.structured_output, "level3_rerank", "json_schema")
    fake_create = AsyncMock(return_value=_make_response("not-json"))
    client = _make_client(fake_create)

    with pytest.raises(StructuredOutputError, match="Failed to parse JSON") as exc_info:
        await call_structured_output(
            client,
            StructuredOutputRequest(
                messages=[{"role": "user", "content": "return json"}],
                response_model=_AdapterPayload,
                call_type="level3_rerank",
                enable_thinking=False,
            ),
        )

    assert exc_info.value.response_text == "not-json"


@pytest.mark.asyncio
async def test_structured_output_schema_validation_error_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    说明: 合法 JSON 但不符合 Pydantic schema 时，应抛错并保留原始响应文本。
    """
    monkeypatch.setattr(settings.structured_output, "mention_extraction", "json_object")
    fake_create = AsyncMock(return_value=_make_response('{"name":"白芷","score":"bad"}'))
    client = _make_client(fake_create, task_type="mention_extraction")

    with pytest.raises(StructuredOutputError) as exc_info:
        await call_structured_output(
            client,
            StructuredOutputRequest(
                messages=[{"role": "user", "content": "请输出 json"}],
                response_model=_AdapterPayload,
                call_type="mention_extraction",
                enable_thinking=False,
            ),
        )

    assert '"score":"bad"' in exc_info.value.response_text
