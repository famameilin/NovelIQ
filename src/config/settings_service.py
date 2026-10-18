"""
设置应用服务

settings.json 与 .env 的写入通道集中在此——用户设置深合并 → 校验 → 稀疏化原子写回 →
原地热生效，以及模型池、嵌入凭据、LTP 目录的受控编辑。HTTP 视图（打码、来源标注、
连通性测试）留在 api 路由
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.config import settings
from src.config.env_file import EnvFileError, apply_env_updates_to_process, read_env_file, update_env_file
from src.config.exceptions import SettingsValidationError
from src.config.schemas.model import _parse_model_pool
from src.config.settings import Settings, apply_settings_onto, diff_user_overrides, serialize_settings

# api_key 打码前缀：写入通道拒收打码值，读侧视图按同一前缀打码
API_KEY_MASK_PREFIX = "••••"

# 单任务组凭据键：补丁字段名 → .env 键名
TASK_ENV_KEYS: dict[str, tuple[str, str, str]] = {
    "EMBEDDING_MODEL": ("EMBEDDING_MODEL_BASE_URL", "EMBEDDING_MODEL_ID", "EMBEDDING_MODEL_KEY"),
}


def settings_file_path() -> Path:
    """与 Settings.from_json 默认路径同语义（CWD 相对），测试注入点"""
    return Path("config/settings.json")


def env_file_path() -> Path:
    """凭据落点：.env 单处，测试注入点"""
    return Path(".env")


def load_settings_file() -> dict[str, Any]:
    """读取 settings.json 现值（不存在或非法时按空覆盖处理并显式报错）"""
    path = settings_file_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SettingsValidationError(f"settings.json 不是合法 JSON，无法解析: {exc}") from exc
    return data if isinstance(data, dict) else {}


def write_settings_file(data: dict[str, Any]) -> None:
    """原子写回 settings.json（临时文件 + replace，避免半截文件）"""
    path = settings_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """按 dict 递归合并，非 dict 值整体覆盖"""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def save_user_settings(values: dict[str, Any]) -> None:
    """保存用户设置：深合并 → 校验（快速失败）→ 稀疏化原子写回 → 原地热生效

    diff 基线用不含 env 叠加的解析实例：env 注入值（凭据/LTP 目录）不是"用户设置"，
    不得经 diff 落进 settings.json
    """
    merged = deep_merge(load_settings_file(), values)
    try:
        candidate = Settings.from_config_dict(merged)
    except ValueError as exc:
        raise SettingsValidationError(str(exc)) from exc

    sparse = diff_user_overrides(serialize_settings(Settings.parse_from_dict(merged)), serialize_settings(Settings()))
    write_settings_file(sparse)
    apply_settings_onto(settings, candidate)


def iteration_budget_info(task: str) -> tuple[int, str]:
    """执行启动时固定预算，并区分文件覆盖、代码默认和当前进程覆盖"""
    actual = getattr(settings.models, task).max_iterations
    file_value = load_settings_file().get("models", {}).get(task, {}).get("max_iterations")
    default = getattr(Settings().models, task).max_iterations
    source = (
        "config/settings.json" if file_value == actual else "code_default" if actual == default else "runtime_override"
    )
    return actual, source


def resolve_task_env_updates(
    env_group: str,
    patch: Mapping[str, str | None] | None,
) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """解析单任务组补丁 → (env 文件更新, 单例终态)

    终态 dict 语义：key → None 表示清除。返回 ({}, {}) 表示本组无操作。
    """
    keys = dict(zip(("base_url", "model", "api_key"), TASK_ENV_KEYS[env_group], strict=True))
    if patch is None:
        return {}, {}

    env_path = env_file_path()
    current_env = read_env_file(env_path)
    base_url = patch.get("base_url")
    model = patch.get("model")
    api_key = patch.get("api_key")

    if api_key == "":
        if (base_url is not None and base_url != "") or (model is not None and model != ""):
            raise SettingsValidationError(f"{env_group} 清空凭据时不可同时设置其他字段")
        return dict.fromkeys(keys.values()), dict.fromkeys(keys)

    updates: dict[str, str | None] = {}
    final: dict[str, str | None] = {}
    for field_name, value in (("base_url", base_url), ("model", model)):
        if value is not None:
            if not value.strip():
                raise SettingsValidationError(f"{keys[field_name]} 不能为空")
            updates[keys[field_name]] = value
            final[field_name] = value
        else:
            final[field_name] = os.environ.get(keys[field_name]) or current_env.get(keys[field_name])

    if api_key is not None:
        if not api_key.strip():
            raise SettingsValidationError(f"{keys['api_key']} 不能为空")
        updates[keys["api_key"]] = api_key
        final["api_key"] = api_key
    else:
        final["api_key"] = os.environ.get(keys["api_key"]) or current_env.get(keys["api_key"])

    # 完整性：本组已配置过（或本次将写入任一字段）时，三键终态必须齐全
    group_configured = bool(updates) or any(os.environ.get(key) or current_env.get(key) for key in keys.values())
    required = ("base_url", "model", "api_key")
    if group_configured and any(not final[field] for field in required):
        missing = [keys[field] for field in required if not final[field]]
        raise SettingsValidationError(f"{env_group} 配置不完整，缺少: {', '.join(missing)}")

    if group_configured:
        updates.update({key: final[field] for field, key in keys.items() if final[field] is not None})
    return updates, final


def apply_task_env_final(final: dict[str, str | None] | None, task_settings: tuple[Any, ...]) -> None:
    """把嵌入凭据终态原地写入单例，清空时显式置 None"""
    if final is None:
        return
    for task in task_settings:
        task.base_url = final.get("base_url")
        task.model = final.get("model")
        task.api_key = final.get("api_key")


def _resolve_model_pool(model_pool: list[dict[str, Any]] | None) -> list[Any]:
    """校验池内模型编辑：同组不可重复编辑、改动已有模型须存在、Key 不接受打码值"""
    if model_pool is None:
        return list(settings.models.model_pool)

    saved_by_id = {entry.model_id: entry for entry in settings.models.model_pool}
    entries: list[dict[str, Any]] = []
    origins: set[str] = set()
    for entry in model_pool:
        original_id = (entry.get("original_model_id") or entry["model_id"]).strip()
        if original_id in origins:
            raise SettingsValidationError("同一已保存模型不能重复编辑")
        origins.add(original_id)
        saved = saved_by_id.get(original_id)
        if entry.get("original_model_id") is not None and saved is None:
            raise SettingsValidationError("要编辑的模型不存在，请重新加载设置")
        api_key = entry.get("api_key") if entry.get("api_key") is not None else saved.api_key if saved else None
        if api_key and api_key.startswith(API_KEY_MASK_PREFIX):
            raise SettingsValidationError("模型 Key 不能使用打码值")
        entries.append(
            {
                "model_id": entry["model_id"],
                "base_url": entry["base_url"],
                "api_key": api_key,
                "weight": entry["weight"],
                "max_in_flight": entry["max_in_flight"],
                "temperature": entry["temperature"],
                "top_p": entry["top_p"],
                "max_tokens": entry["max_tokens"],
            }
        )
    try:
        return _parse_model_pool(entries)
    except ValueError as exc:
        raise SettingsValidationError(str(exc)) from exc


def _resolve_ltp_update(ltp_model_dir: str | None) -> dict[str, str | None]:
    if ltp_model_dir is None:
        return {}
    if ltp_model_dir == "":
        return {"LTP_MODEL_DIR": None}
    if not Path(ltp_model_dir).is_dir():
        raise SettingsValidationError(f"LTP_MODEL_DIR 目录不存在: {ltp_model_dir}")
    return {"LTP_MODEL_DIR": ltp_model_dir}


def update_model_env(
    *,
    model_pool: list[dict[str, Any]] | None,
    diagnosis_model_id: str | None,
    diagnosis_model_id_provided: bool,
    embedding: Mapping[str, str | None] | None,
    ltp_model_dir: str | None,
) -> None:
    """保存模型凭据与参数：写 .env 白名单键 + 同步 os.environ + 单例原地生效"""
    pool_updates: dict[str, str | None] = {}
    candidate_pool = _resolve_model_pool(model_pool)
    if model_pool is not None:
        pool_updates["MODEL_POOL"] = json.dumps([asdict(entry) for entry in candidate_pool], ensure_ascii=False)

    diagnosis_id = settings.models.diagnosis_model_id
    if diagnosis_model_id_provided:
        diagnosis_id = diagnosis_model_id.strip() if diagnosis_model_id else None
        pool_updates["DIAGNOSIS_MODEL_ID"] = diagnosis_id
    if diagnosis_id and not any(entry.model_id == diagnosis_id for entry in candidate_pool):
        raise SettingsValidationError("请从模型池指定诊断模型，不能删除仍被诊断使用的模型")

    embedding_updates, embedding_final = resolve_task_env_updates("EMBEDDING_MODEL", embedding)
    ltp_update = _resolve_ltp_update(ltp_model_dir)

    updates = {**pool_updates, **embedding_updates, **ltp_update}
    if updates:
        try:
            update_env_file(env_file_path(), updates)
        except EnvFileError as exc:
            raise SettingsValidationError(str(exc)) from exc
        apply_env_updates_to_process(updates)

    settings.models.model_pool = candidate_pool
    settings.models.diagnosis_model_id = diagnosis_id
    apply_task_env_final(embedding_final or None, (settings.models.paragraph_embedding,))
    if ltp_model_dir is not None:
        settings.linguistic.ltp.model_dir = ltp_model_dir or None
