"""设置端点（/api/settings）

只承担 HTTP 契约：字段注册表与生效值视图（默认值 ← settings.json ← env 凭据）、设置保存、
凭据受控编辑与连接测试。写盘与热生效逻辑在 src/config/settings_service.py。
"""
from __future__ import annotations

import time
from copy import deepcopy
from threading import RLock
from typing import Any

from fastapi import APIRouter, HTTPException
from openai import OpenAI

from src.api.models.settings import (
    ModelEnvUpdateRequest,
    ModelProviderTestRequest,
    ModelProviderTestResponse,
    SettingFieldSpecResponse,
    SettingSectionSpecResponse,
    SettingsSchemaResponse,
    SettingsViewResponse,
    UpdateSettingsRequest,
)
from src.config import settings, settings_service
from src.config.schemas.model import EmbeddingModelSettings, WeightedModelSettings
from src.config.settings import Settings, serialize_settings
from src.config.settings_registry import SETTING_FIELDS, SETTING_SECTIONS
from src.config.settings_service import API_KEY_MASK_PREFIX

router = APIRouter(prefix="/settings", tags=["settings"])

_TEST_CONNECT_TIMEOUT_S = 10.0
_TEST_CONNECT_MAX_MODELS = 20
_SETTINGS_LOCK = RLock()


def _get_value_at(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for segment in path:
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _mask_secret_value(value: Any) -> Any:
    if isinstance(value, str) and value:
        suffix = value[-4:] if len(value) > 4 else ""
        return f"{API_KEY_MASK_PREFIX}{suffix}"
    return value


def _mask_secrets(data: dict[str, Any]) -> dict[str, Any]:
    """api_key 明文不出 API：一律打码为 "••••" + 尾 4 位"""

    def _walk(node: dict[str, Any]) -> dict[str, Any]:
        masked: dict[str, Any] = {}
        for key, value in node.items():
            if key == "api_key":
                masked[key] = _mask_secret_value(value)
            elif isinstance(value, dict):
                masked[key] = _walk(value)
            elif isinstance(value, list):
                masked[key] = [_walk(item) if isinstance(item, dict) else item for item in value]
            else:
                masked[key] = value
        return masked

    return _walk(data)


def _collect_sources(file_data: dict[str, Any]) -> dict[str, str]:
    """逐字段来源：文件中存在该路径 = 用户覆盖（file），否则为代码默认"""
    return {
        "/".join(spec.path): ("file" if _get_value_at(file_data, spec.path) is not None else "default")
        for spec in SETTING_FIELDS
    }


def _view_response() -> SettingsViewResponse:
    file_data = settings_service.load_settings_file()
    defaults = serialize_settings(Settings())
    return SettingsViewResponse(
        values=_mask_secrets(deepcopy(serialize_settings(settings))),
        defaults=defaults,
        sources=_collect_sources(file_data),
    )


def _save_user_settings(request: UpdateSettingsRequest) -> SettingsViewResponse:
    settings_service.save_user_settings(request.values)
    return _view_response()


def _update_model_env(request: ModelEnvUpdateRequest) -> SettingsViewResponse:
    settings_service.update_model_env(
        model_pool=[entry.model_dump() for entry in request.model_pool] if request.model_pool is not None else None,
        diagnosis_model_id=request.diagnosis_model_id,
        diagnosis_model_id_provided="diagnosis_model_id" in request.model_fields_set,
        embedding=request.embedding_model.model_dump() if request.embedding_model is not None else None,
        ltp_model_dir=request.ltp_model_dir,
    )
    return _view_response()


@router.get("/schema", response_model=SettingsSchemaResponse)
def get_settings_schema() -> SettingsSchemaResponse:
    """字段注册表：前端按此自动渲染表单，默认值经 values/defaults 视图合并输出"""
    return SettingsSchemaResponse(
        sections=[SettingSectionSpecResponse(**section.__dict__) for section in SETTING_SECTIONS],
        fields=[
            SettingFieldSpecResponse(
                path=list(spec.path),
                field_type=spec.field_type,
                label=spec.label,
                description=spec.description,
                min_value=spec.min_value,
                max_value=spec.max_value,
                step=spec.step,
                enum_values=list(spec.enum_values),
                nullable=spec.nullable,
                editable=spec.editable,
            )
            for spec in SETTING_FIELDS
        ],
    )


@router.get("", response_model=SettingsViewResponse)
def get_settings() -> SettingsViewResponse:
    """生效值（api_key 打码）+ 代码默认值 + 逐字段来源"""
    with _SETTINGS_LOCK:
        return _view_response()


@router.put("", response_model=SettingsViewResponse)
def update_settings(request: UpdateSettingsRequest) -> SettingsViewResponse:
    """保存用户设置：深合并 → 校验 → 稀疏化原子写回 → 原地热生效"""
    with _SETTINGS_LOCK:
        return _save_user_settings(request)


@router.put("/env", response_model=SettingsViewResponse)
def update_model_env(request: ModelEnvUpdateRequest) -> SettingsViewResponse:
    """串行保存凭据与参数，避免并发写临时文件或覆盖已更新的运行配置"""
    with _SETTINGS_LOCK:
        return _update_model_env(request)


@router.post("/model-providers/{task}/test", response_model=ModelProviderTestResponse)
def test_model_provider(task: str, request: ModelProviderTestRequest | None = None) -> ModelProviderTestResponse:
    """测试模型服务连通性（GET /v1/models，字段缺省用当前生效配置；明文凭据仅本次请求内存使用）"""
    if task not in {"pool", "embedding"}:
        raise HTTPException(status_code=404, detail=f"未知任务组: {task}")
    saved: EmbeddingModelSettings | WeightedModelSettings | None
    if task == "embedding":
        saved = settings.models.paragraph_embedding
    else:
        saved = next((entry for entry in settings.models.model_pool
                      if request and entry.model_id == request.model_id), None)
    credentials = {"base_url": saved.base_url if saved else None, "api_key": saved.api_key if saved else None}
    base_url = (request.base_url if request and request.base_url else credentials["base_url"]) or ""
    api_key = (request.api_key if request and request.api_key else credentials["api_key"]) or ""

    if not base_url:
        return ModelProviderTestResponse(ok=False, error="base_url 未配置")
    if not api_key:
        return ModelProviderTestResponse(ok=False, error="Key 未配置")

    try:
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=_TEST_CONNECT_TIMEOUT_S, max_retries=0)
        started = time.monotonic()
        models = list(client.models.list())
        latency_ms = (time.monotonic() - started) * 1000
        return ModelProviderTestResponse(
            ok=True,
            latency_ms=round(latency_ms, 1),
            model_ids=[model.id for model in models][:_TEST_CONNECT_MAX_MODELS],
        )
    except Exception as exc:  # 连接失败原因直接回显给设置页
        error = str(exc).replace(api_key, "[redacted]") if api_key else str(exc)
        return ModelProviderTestResponse(ok=False, error=error[:300])


__all__ = ["router"]
