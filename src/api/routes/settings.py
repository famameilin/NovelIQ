"""2026-09-10 设置端点（/api/settings）

三条通道的落地：
- GET /schema、GET /：字段注册表 + 生效值视图（默认值 ← settings.json ← env 凭据）
- PUT /：用户设置保存——与文件现值深合并 → 解析校验（快速失败 422）→ 稀疏化
  原子写回 settings.json → 原地变更运行时单例字段（热生效，不做重启标记）
- PUT /env、POST /model-providers/{task}/test：模型凭据受控编辑与连接测试。
  key 只存 .env 一处（runtime_env 单一解析边界），本路由写文件的同时
  显式同步 os.environ 并把终态原地写入单例——因为写文件本身不会让
  进程生效（load_dotenv 只在 import 期执行一次）。清空嵌入凭据时须显式置空。
"""

from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import APIRouter, HTTPException
from openai import OpenAI

from src.api.exceptions import SettingsValidationError
from src.api.models.settings import (
    ModelEnvUpdateRequest,
    ModelProviderTestRequest,
    ModelProviderTestResponse,
    SettingFieldSpecResponse,
    SettingSectionSpecResponse,
    SettingsSchemaResponse,
    SettingsViewResponse,
    TaskEnvPatchRequest,
    UpdateSettingsRequest,
)
from src.config import settings
from src.config.env_file import EnvFileError, apply_env_updates_to_process, read_env_file, update_env_file
from src.config.schemas.model import EmbeddingModelSettings, WeightedModelSettings, _parse_model_pool
from src.config.settings import (
    Settings,
    apply_settings_onto,
    diff_user_overrides,
    serialize_settings,
)
from src.config.settings_registry import (
    SETTING_FIELDS,
    SETTING_SECTIONS,
)

router = APIRouter(prefix="/settings", tags=["settings"])

_API_KEY_MASK_PREFIX = "••••"
_TEST_CONNECT_TIMEOUT_S = 10.0
_TEST_CONNECT_MAX_MODELS = 20
_SETTINGS_LOCK = RLock()

# env 凭据在 dataclass 上的注入路径仅用于文档说明；diff 基线用不含 env 的
# parse_from_dict 实例（见 PUT /），从源头保证 env 值不落 settings.json

_TASK_ENV_KEYS: dict[str, tuple[str, str, str]] = {
    "EMBEDDING_MODEL": ("EMBEDDING_MODEL_BASE_URL", "EMBEDDING_MODEL_ID", "EMBEDDING_MODEL_KEY"),
}


def _settings_file_path() -> Path:
    """与 Settings.from_json 默认路径同语义（CWD 相对），测试注入点"""
    return Path("config/settings.json")


def _env_file_path() -> Path:
    return Path(".env")


def _load_file_data() -> dict[str, Any]:
    path = _settings_file_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SettingsValidationError(f"settings.json 不是合法 JSON，无法解析: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _write_settings_file(data: dict[str, Any]) -> None:
    path = _settings_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _get_value_at(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for segment in path:
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


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


def _mask_secret_value(value: Any) -> Any:
    if isinstance(value, str) and value:
        suffix = value[-4:] if len(value) > 4 else ""
        return f"{_API_KEY_MASK_PREFIX}{suffix}"
    return value


def _collect_sources(file_data: dict[str, Any]) -> dict[str, str]:
    """逐字段来源：文件中存在该路径 = 用户覆盖（file），否则为代码默认"""
    return {
        "/".join(spec.path): ("file" if _get_value_at(file_data, spec.path) is not None else "default")
        for spec in SETTING_FIELDS
    }


def _view_response() -> SettingsViewResponse:
    file_data = _load_file_data()
    defaults = serialize_settings(Settings())
    return SettingsViewResponse(
        values=_mask_secrets(deepcopy(serialize_settings(settings))),
        defaults=defaults,
        sources=_collect_sources(file_data),
    )


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
        return _update_settings(request)


def _update_settings(request: UpdateSettingsRequest) -> SettingsViewResponse:
    file_data = _load_file_data()
    merged = _deep_merge(file_data, request.values)
    try:
        candidate = Settings.from_config_dict(merged)
    except ValueError as exc:
        raise SettingsValidationError(str(exc)) from exc

    # diff 基线用不含 env 叠加的解析实例：env 注入值（凭据/LTP 目录）不是
    # "用户设置"，不得经 diff 落进 settings.json
    sparse = diff_user_overrides(serialize_settings(Settings.parse_from_dict(merged)), serialize_settings(Settings()))
    _write_settings_file(sparse)
    apply_settings_onto(settings, candidate)
    return _view_response()


def _resolve_task_env_updates(
    env_group: str, patch: TaskEnvPatchRequest | None,
) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """解析单任务组补丁 → (env 文件更新, 单例终态)

    终态 dict 语义：key → None 表示清除。返回 ({}, {}) 表示本组无操作。
    """
    keys = dict(zip(("base_url", "model", "api_key"), _TASK_ENV_KEYS[env_group], strict=True))
    if patch is None:
        return {}, {}

    env_path = _env_file_path()
    current_env = read_env_file(env_path)

    if patch.api_key == "":
        if (patch.base_url is not None and patch.base_url != "") or (patch.model is not None and patch.model != ""):
            raise SettingsValidationError(f"{env_group} 清空凭据时不可同时设置其他字段")
        return dict.fromkeys(keys.values()), dict.fromkeys(keys)

    updates: dict[str, str | None] = {}
    final: dict[str, str | None] = {}
    for field_name in ("base_url", "model"):
        value = getattr(patch, field_name)
        if value is not None:
            if not value.strip():
                raise SettingsValidationError(f"{keys[field_name]} 不能为空")
            updates[keys[field_name]] = value
            final[field_name] = value
        else:
            final[field_name] = os.environ.get(keys[field_name]) or current_env.get(keys[field_name])

    if patch.api_key is not None:
        if not patch.api_key.strip():
            raise SettingsValidationError(f"{keys['api_key']} 不能为空")
        updates[keys["api_key"]] = patch.api_key
        final["api_key"] = patch.api_key
    else:
        final["api_key"] = os.environ.get(keys["api_key"]) or current_env.get(keys["api_key"])

    # 完整性：本组已配置过（或本次将写入任一字段）时，三键终态必须齐全
    group_configured = bool(updates) or any(
        os.environ.get(key) or current_env.get(key) for key in keys.values()
    )
    required = ("base_url", "model", "api_key")
    if group_configured and any(not final[field] for field in required):
        missing = [keys[field] for field in required if not final[field]]
        raise SettingsValidationError(f"{env_group} 配置不完整，缺少: {', '.join(missing)}")

    if group_configured:
        updates.update({key: final[field] for field, key in keys.items() if final[field] is not None})
    return updates, final


def _apply_task_env_final(
    final: dict[str, str | None] | None, task_settings: tuple[Any, ...]
) -> None:
    """把嵌入凭据终态原地写入单例，清空时显式置 None"""
    if final is None:
        return
    for task in task_settings:
        task.base_url = final.get("base_url")
        task.model = final.get("model")
        task.api_key = final.get("api_key")


@router.put("/env", response_model=SettingsViewResponse)
def update_model_env(request: ModelEnvUpdateRequest) -> SettingsViewResponse:
    """串行保存凭据与参数，避免并发写临时文件或覆盖已更新的运行配置"""
    with _SETTINGS_LOCK:
        return _update_model_env(request)


def _update_model_env(request: ModelEnvUpdateRequest) -> SettingsViewResponse:
    pool_updates: dict[str, str | None] = {}
    candidate_pool = settings.models.model_pool
    if request.model_pool is not None:
        saved_by_id = {entry.model_id: entry for entry in settings.models.model_pool}
        entries: list[dict[str, Any]] = []
        origins: set[str] = set()
        for entry in request.model_pool:
            original_id = (entry.original_model_id or entry.model_id).strip()
            if original_id in origins:
                raise SettingsValidationError("同一已保存模型不能重复编辑")
            origins.add(original_id)
            saved = saved_by_id.get(original_id)
            if entry.original_model_id is not None and saved is None:
                raise SettingsValidationError("要编辑的模型不存在，请重新加载设置")
            api_key = entry.api_key if entry.api_key is not None else saved.api_key if saved is not None else None
            if api_key and api_key.startswith(_API_KEY_MASK_PREFIX):
                raise SettingsValidationError("模型 Key 不能使用打码值")
            entries.append({
                "model_id": entry.model_id, "base_url": entry.base_url, "api_key": api_key,
                "weight": entry.weight, "max_in_flight": entry.max_in_flight,
                # 2026-10-02 设置迁移：采样参数随模型保存
                "temperature": entry.temperature, "top_p": entry.top_p, "max_tokens": entry.max_tokens,
            })
        try:
            candidate_pool = _parse_model_pool(entries)
        except ValueError as exc:
            raise SettingsValidationError(str(exc)) from exc
        pool_updates["MODEL_POOL"] = json.dumps([asdict(entry) for entry in candidate_pool], ensure_ascii=False)
    diagnosis_id = settings.models.diagnosis_model_id
    if "diagnosis_model_id" in request.model_fields_set:
        diagnosis_id = request.diagnosis_model_id.strip() if request.diagnosis_model_id else None
        pool_updates["DIAGNOSIS_MODEL_ID"] = diagnosis_id
    if diagnosis_id and not any(entry.model_id == diagnosis_id for entry in candidate_pool):
        raise SettingsValidationError("请从模型池指定诊断模型，不能删除仍被诊断使用的模型")
    embedding_updates, embedding_final = _resolve_task_env_updates("EMBEDDING_MODEL", request.embedding_model)

    ltp_update: dict[str, str | None] = {}
    if request.ltp_model_dir is not None:
        if request.ltp_model_dir == "":
            ltp_update = {"LTP_MODEL_DIR": None}
        else:
            if not Path(request.ltp_model_dir).is_dir():
                raise SettingsValidationError(f"LTP_MODEL_DIR 目录不存在: {request.ltp_model_dir}")
            ltp_update = {"LTP_MODEL_DIR": request.ltp_model_dir}

    updates = {**pool_updates, **embedding_updates, **ltp_update}
    if updates:
        try:
            update_env_file(_env_file_path(), updates)
        except EnvFileError as exc:
            raise SettingsValidationError(str(exc)) from exc
        apply_env_updates_to_process(updates)

    settings.models.model_pool = candidate_pool
    settings.models.diagnosis_model_id = diagnosis_id
    _apply_task_env_final(embedding_final or None, (settings.models.paragraph_embedding,))
    if request.ltp_model_dir is not None:
        settings.linguistic.ltp.model_dir = request.ltp_model_dir or None

    return _view_response()


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
