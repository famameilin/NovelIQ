"""
BaseModelClient 结构化解析辅助模块。

创建时间: 2026-04-23
任务: p2-base-model-client-split
说明: 从 base.py 中拆出响应内容提取、JSON 兼容解析与结构化校验逻辑。
"""

from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger
from pydantic import BaseModel

from src.models.local.parser import try_parse_json
from src.models.local.parser.foreshadowing import parse_foreshadowing_result
from src.models.local.parser.thinking import extract_thinking_unified
from src.models.local.schema import ForeshadowingResult


def parse_structured_response[T: BaseModel](response: Any, response_model: type[T]) -> T:
    """
    将模型响应解析并校验为指定 Pydantic 模型。

    创建时间: 2026-04-23
    任务: p2-base-model-client-split
    新建原因: 将 strict JSON 解析与 validation 错误日志从 BaseModelClient 主类中拆离。
    """
    if not response.choices:
        raise ValueError("Empty response from API")

    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty content in response")

    if not isinstance(content, str):
        raise ValueError(f"Content must be a string, got {type(content).__name__}")

    json_data = try_parse_json(content)
    if json_data is None:
        raise ValueError(f"Failed to parse JSON from response: {content[:200]}")

    try:
        if response_model is ForeshadowingResult:
            # 中文注释：Phase2 需要先经过专用归一化，
            # 把“弱阳性但非强 setup”的热路径脏输出降级成合法 negative，
            # 避免通用 model_validate 直接抛错后触发整轮重试。
            return parse_foreshadowing_result(json_data)  # type: ignore[return-value]
        return response_model.model_validate(json_data)
    except Exception as exc:
        logger.error(
            "Structured response validation failed: model={}, error={}, json_data={}, raw_content={}",
            response_model.__name__,
            str(exc),
            json_data,
            content,
        )
        raise


def extract_response_content(message: Any) -> tuple[str, str | None]:
    """
    从 message 中提取正文与 thinking 内容。

    创建时间: 2026-04-23
    任务: p2-base-model-client-split
    新建原因: 统一 BaseModelClient 及 token 估算补记路径对响应文本的理解方式。
    """
    content = message.content or ""
    extraction = extract_thinking_unified(
        content=content,
        reasoning_content=getattr(message, "reasoning_content", None),
        support_reasoning_content=True,
        support_think_tags=True,
    )
    return extraction.content_without_thinking, extraction.thinking_content


def parse_response(content: str) -> dict[str, Any] | None:
    """
    兼容 markdown 代码块与混合文本场景下的 JSON 解析。

    创建时间: 2026-04-23
    任务: p2-base-model-client-split
    新建原因: 把 BaseModelClient 的宽松 JSON 提取逻辑变成独立纯函数，便于单测和复用。
    """
    content_to_parse = content.strip()
    if not content_to_parse:
        return None

    try:
        data = json.loads(content_to_parse)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content_to_parse)
    if json_match:
        extracted = json_match.group(1).strip()
        try:
            data = json.loads(extracted)
            if isinstance(data, dict):
                logger.info("[模型] JSON从markdown代码块中提取成功")
                return data
        except json.JSONDecodeError:
            pass

    json_match = re.search(r"\{[\s\S]*\}", content_to_parse)
    if json_match:
        extracted = json_match.group(0)
        try:
            data = json.loads(extracted)
            if isinstance(data, dict):
                logger.info("[模型] JSON从混合内容中提取成功")
                return data
        except json.JSONDecodeError:
            pass

    return None
