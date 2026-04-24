"""
Instructor 结构化输出封装。

创建时间: 2026-04-24
任务: structured-output-adapter-instructor-unification
说明: 只在项目级适配层内部接触 Instructor，业务模块仍通过 BaseModelClient 进入模型运行时。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

try:
    import instructor
except ImportError:  # pragma: no cover - 项目依赖缺失时由运行时抛出清晰错误。
    instructor = None  # type: ignore[assignment]


async def call_with_instructor_json[T: BaseModel](
    client: Any,
    *,
    request_params: dict[str, Any],
    response_model: type[T],
) -> tuple[T, Any]:
    """
    使用 Instructor JSON mode 执行结构化调用。

    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    新建原因: 复用 Instructor 的 Pydantic 解析能力，同时通过 create_with_completion 保留 raw completion，
              避免丢失 thinking、reasoning tokens 和审计所需响应对象。
    """
    if instructor is None:
        raise RuntimeError("instructor dependency is required for structured_output mode instructor_json")

    instructor_client = instructor.from_openai(client._client, mode=instructor.Mode.JSON)
    parsed, raw_completion = await instructor_client.chat.completions.create_with_completion(
        response_model=response_model,
        max_retries=1,
        **request_params,
    )
    return parsed, raw_completion
