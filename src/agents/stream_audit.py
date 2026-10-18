"""
单次模型调用计时与 Provider 请求元数据

包含 ModelCallTiming、模型地址与工具合同脱敏工具、物理 Provider 请求元数据构造；
经 stream.py re-export。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True, slots=True)
class ModelCallTiming:
    """用于保存单次模型调用的逐项计时（毫秒）与计时口径备注"""

    ttft_ms: int | None = None
    first_visible_ms: int | None = None
    reasoning_ms: int | None = None
    model_ms: int | None = None
    timing_notes: tuple[str, ...] = ()


def _safe_base_url(value: Any) -> str | None:
    """用于清除模型地址中可能出现的认证信息后再写入审计"""
    if not value:
        return None
    try:
        parsed = urlsplit(str(value))
    except ValueError:
        return "invalid-url"
    if not parsed.scheme or not parsed.netloc:
        return "invalid-url"
    return urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", ""))


def _sanitize_audit_value(value: Any) -> Any:
    """用于递归移除工具合同中可能出现的认证字段后再计算指纹"""
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_audit_value(item)
            for key, item in value.items()
            if not _is_sensitive_audit_key(str(key))
        }
    if isinstance(value, list | tuple):
        return [_sanitize_audit_value(item) for item in value]
    return value


def _is_sensitive_audit_key(key: str) -> bool:
    """用于识别下划线连字符前缀等变体的认证字段名称"""
    normalized = "".join(character for character in key.lower() if character.isalnum())
    return any(
        marker in normalized
        for marker in ("apikey", "authorization", "accesstoken", "clientsecret", "password", "secret", "token")
    )


def _safe_tool_contract(tools: Any) -> tuple[list[str], str]:
    """用于生成脱敏的绑定工具合同摘要和稳定指纹"""
    if not isinstance(tools, list):
        return [], hashlib.sha256(b"[]").hexdigest()
    normalized: list[Any] = []
    names: list[str] = []
    for tool in tools:
        if isinstance(tool, Mapping):
            function = tool.get("function")
            name = function.get("name") if isinstance(function, Mapping) else tool.get("name")
            if name:
                names.append(str(name))
            normalized.append(_sanitize_audit_value(tool))
            continue
        name = getattr(tool, "name", None)
        if name:
            names.append(str(name))
        args_schema = getattr(tool, "args_schema", None)
        model_json_schema = getattr(args_schema, "model_json_schema", None)
        schema = model_json_schema() if callable(model_json_schema) else None
        normalized.append(_sanitize_audit_value({"name": str(name or "unknown"), "parameters": schema}))
    canonical = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return sorted(set(names)), hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _provider_request_metadata(model: Any, *, attempt: int) -> dict[str, Any]:
    """用于生成不含密钥的物理 Provider 请求参数与配置指纹

    调用固定为流式传输（transport 恒为 "stream"）。
    """
    bound_model = getattr(model, "bound", model)
    model_kwargs = getattr(bound_model, "model_kwargs", None) or {}
    extra_body = model_kwargs.get("extra_body") if isinstance(model_kwargs, Mapping) else None
    if not isinstance(extra_body, Mapping):
        extra_body = getattr(bound_model, "extra_body", None) or {}
    binding_kwargs = getattr(model, "kwargs", None) or {}
    tools = binding_kwargs.get("tools") if isinstance(binding_kwargs, Mapping) else None
    tool_names, tool_contract_fingerprint = _safe_tool_contract(tools)
    thinking = bool(extra_body.get("think")) if isinstance(extra_body, Mapping) else False
    parameters: dict[str, Any] = {
        "model": str(getattr(bound_model, "model_name", None) or getattr(bound_model, "model", "") or "unknown"),
        "base_url": _safe_base_url(
            getattr(bound_model, "base_url", None) or getattr(bound_model, "openai_api_base", None)
        ),
        "temperature": getattr(bound_model, "temperature", None),
        "top_p": getattr(bound_model, "top_p", None),
        "timeout_s": getattr(bound_model, "request_timeout", None) or getattr(bound_model, "timeout", None),
        "streaming": bool(getattr(bound_model, "streaming", True)),
        "extra_body": {"think": thinking},
        "tool_names": tool_names,
        "tool_contract_fingerprint": tool_contract_fingerprint,
    }
    canonical = json.dumps(parameters, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "request_index": attempt,
        "attempt": attempt,
        "transport": "stream",
        "parameters": parameters,
        "config_fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "timing_contract": {
            "ttft_ms": "本物理请求从发送到首个 reasoning正文或工具 payload 的毫秒数",
            "model_ms": "本物理请求从发送到流结束或错误的墙钟毫秒数",
        },
    }
