from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.config import TaskModelConfig
from src.models.annotation import AnnotationClient
from src.models.local.base import BaseModelClient
from src.models.local.schema import ForeshadowingResult


class _DummyClient:
    """
    轻量 stub，用于验证统一估算 token helper。

    创建时间: 2026-04-22
    创建者: Codex
    任务: unify-estimated-token-accounting
    说明: 直接复用 BaseModelClient 的实例方法，不依赖真实网络客户端。
    """

    def __init__(self, *, task_type: str, model: str = "test-model", novel_id: str = "novel-1") -> None:
        self._task_type = task_type
        self._config = SimpleNamespace(model=model)
        self._novel_id = novel_id
        self.recorded_calls: list[dict[str, object]] = []
        self._token_usage_callback = self._capture_usage

    def _capture_usage(
        self,
        novel_id: str,
        task_type: str,
        call_type: str,
        model: str,
        prompt_tokens: int,
        total_tokens: int,
        completion_tokens: int | None,
        chunk_id: int | None,
    ) -> None:
        self.recorded_calls.append(
            {
                "novel_id": novel_id,
                "task_type": task_type,
                "call_type": call_type,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "total_tokens": total_tokens,
                "completion_tokens": completion_tokens,
                "chunk_id": chunk_id,
            }
        )


def test_estimated_token_accounting_is_consistent_across_task_types() -> None:
    """
    创建时间: 2026-04-22
    创建者: Codex
    任务: unify-estimated-token-accounting
    说明: 同一组 prompt/response 在不同任务类型下，估算 token 数应一致，
          只允许 task_type / call_type 元数据不同。
    """
    messages = [
        {"role": "system", "content": "你是一个测试助手。"},
        {"role": "user", "content": "请输出一个很短的 JSON。"},
    ]
    response_text = '{"ok": true}'

    annotation_client = _DummyClient(task_type="annotation")
    diagnosis_client = _DummyClient(task_type="diagnosis")

    BaseModelClient._record_estimated_token_usage_from_messages(
        annotation_client,
        messages,
        response_text,
        "phase1",
        7,
    )
    BaseModelClient._record_estimated_token_usage_from_messages(
        diagnosis_client,
        messages,
        response_text,
        "diagnosis",
        None,
    )

    annotation_usage = annotation_client.recorded_calls[0]
    diagnosis_usage = diagnosis_client.recorded_calls[0]

    assert annotation_usage["prompt_tokens"] == diagnosis_usage["prompt_tokens"]
    assert annotation_usage["completion_tokens"] == diagnosis_usage["completion_tokens"]
    assert annotation_usage["total_tokens"] == diagnosis_usage["total_tokens"]
    assert annotation_usage["task_type"] == "annotation"
    assert diagnosis_usage["task_type"] == "diagnosis"


def test_estimated_token_accounting_handles_empty_response_text() -> None:
    """
    创建时间: 2026-04-22
    创建者: Codex
    任务: unify-estimated-token-accounting
    说明: 空 completion 也应正常落账，并且 completion_tokens 至少保持为 0。
    """
    client = _DummyClient(task_type="annotation")
    messages = [{"role": "user", "content": "只返回空字符串"}]

    BaseModelClient._record_estimated_token_usage_from_messages(client, messages, "", "phase2", 3)

    usage = client.recorded_calls[0]
    assert usage["call_type"] == "phase2"
    assert usage["chunk_id"] == 3
    assert usage["completion_tokens"] == 0
    assert usage["total_tokens"] == usage["prompt_tokens"]


def test_estimated_token_accounting_allows_business_task_override() -> None:
    """
    创建时间: 2026-04-22
    创建者: Codex
    任务: fix-token-coverage-fallback-bucket
    说明: fallback 执行客户端可以保留自己的内部 task_type，
          但 token_usage 应允许显式覆盖回 annotation 主业务桶。
    """
    client = _DummyClient(task_type="annotation_fallback")
    messages = [{"role": "user", "content": "请输出一个测试响应"}]

    BaseModelClient._record_estimated_token_usage_from_messages(
        client,
        messages,
        '{"ok": true}',
        "phase1",
        9,
        task_type="annotation",
    )

    usage = client.recorded_calls[0]
    assert usage["task_type"] == "annotation"
    assert usage["call_type"] == "phase1"
    assert usage["chunk_id"] == 9


def test_annotation_fallback_parse_failure_still_records_annotation_bucket() -> None:
    """
    创建时间: 2026-04-22
    创建者: Codex
    任务: fix-token-coverage-fallback-bucket
    说明: fallback annotation client 在结构化解析失败时，原始 token_usage
          也必须直接写回 annotation 主业务桶，不能留下 annotation_fallback 脏数据。

    修改时间: 2026-04-27
    任务: fix-structured-output-token-usage-test
    修改内容: 改为走当前 AnnotationClient 的真实 structured-output 调用面，
    用可 await 的 SDK mock 覆盖解析失败补记 token 路径。
    """
    recorded_calls: list[dict[str, object]] = []

    def token_usage_callback(
        novel_id: str,
        task_type: str,
        call_type: str,
        model: str,
        prompt_tokens: int,
        total_tokens: int,
        completion_tokens: int | None,
        chunk_id: int | None,
    ) -> None:
        recorded_calls.append(
            {
                "novel_id": novel_id,
                "task_type": task_type,
                "call_type": call_type,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "total_tokens": total_tokens,
                "completion_tokens": completion_tokens,
                "chunk_id": chunk_id,
            }
        )

    invalid_response = MagicMock()
    invalid_response.choices = [MagicMock(message=MagicMock(content="not-json"))]
    sdk_client = MagicMock()
    sdk_client.chat.completions.create = AsyncMock(return_value=invalid_response)
    client = AnnotationClient(
        task_type="annotation_fallback",
        config=TaskModelConfig(base_url="http://example.com", model="gpt-test", api_key="k"),
        client=sdk_client,
        token_usage_callback=token_usage_callback,
        novel_id="novel-1",
    )

    try:
        import asyncio

        asyncio.run(
            client._call_annotation_api(
                messages=[{"role": "user", "content": "请输出 JSON"}],
                enable_thinking=False,
                chunk_id=7,
                response_model=ForeshadowingResult,
                call_type="phase2",
            )
        )
    except ValueError:
        pass

    assert len(recorded_calls) == 1
    assert recorded_calls[0]["task_type"] == "annotation"
    assert recorded_calls[0]["call_type"] == "phase2"
    assert recorded_calls[0]["chunk_id"] == 7
