"""2026-09-10 .env 白名单键编辑器（设置页模型凭据通道）

.env 是模型凭据的唯一存储（runtime_env.py 单一解析边界）。
本模块是它的受控编辑器：只允许触碰 MODEL_ENV_KEYS 白名单内的键，
写入保留注释与行序，缺失键追加文件尾，原子替换。

写文件本身不会让进程内生效（load_dotenv 只在 import 期执行一次），
调用方必须同步调用 apply_env_updates_to_process 更新 os.environ，
再经 Settings 的 env 叠加链路原地变更单例——热生效链路见
src/api/routes/settings.py 的 PUT /settings/env。
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from src.config.settings_registry import MODEL_ENV_KEYS

_ENV_LINE_PATTERN = re.compile(r"^\s*(?:(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


class EnvFileError(ValueError):
    """2026-09-10 .env 白名单校验失败（非白名单键或空键名）"""


def _validate_whitelist(updates: Mapping[str, str | None]) -> None:
    illegal = sorted(set(updates) - MODEL_ENV_KEYS)
    if illegal:
        raise EnvFileError(f"以下键不在 .env 可编辑白名单内: {', '.join(illegal)}")


def update_env_file(path: Path, updates: Mapping[str, str | None]) -> None:
    """把 updates 合并进 .env 文件（None = 删除该键行），保留注释与行序

    文件中不存在的键（值为非 None）按声明顺序追加到文件尾部。
    原子写：先写临时文件再 os.replace。
    """
    _validate_whitelist(updates)

    lines: list[str] = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.exists() else []
    pending = dict(updates)
    output: list[str] = []

    for line in lines:
        match = _ENV_LINE_PATTERN.match(line)
        if match is None or match.group(1) not in pending:
            output.append(line)
            continue
        key = match.group(1)
        new_value = pending.pop(key)
        if new_value is None:
            continue
        eol = "\n" if line.endswith("\n") else ""
        output.append(f"{key}={new_value}{eol}")

    for key, value in updates.items():
        if key in pending and value is not None:
            output.append(f"{key}={value}\n")

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text("".join(output), encoding="utf-8")
    os.replace(tmp_path, path)


def read_env_file(path: Path) -> dict[str, str]:
    """读取 .env 中的 KEY=VALUE（忽略注释与空行），供设置页回显打码值"""
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ENV_LINE_PATTERN.match(line)
        if match is not None:
            result[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return result


def apply_env_updates_to_process(updates: Mapping[str, str | None]) -> None:
    """把 updates 同步进当前进程 os.environ（None = 删除），使运行时读取与文件一致"""
    _validate_whitelist(updates)
    for key, value in updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
