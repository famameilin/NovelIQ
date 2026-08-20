"""
主题模型路径解析

所有主题模型读写都通过本模块解析项目根目录，避免依赖进程当前工作目录
"""

from __future__ import annotations

from pathlib import Path


def _find_project_root(start: Path) -> Path:
    """2026-08-20 从给定目录向上查找包含项目配置的根目录"""
    resolved_start = start.resolve()
    for candidate in (resolved_start, *resolved_start.parents):
        if (candidate / "config" / "settings.json").is_file():
            return candidate
    raise RuntimeError(
        "无法定位项目根目录：祖先目录中未找到 config/settings.json"
    )


def resolve_project_root() -> Path:
    """2026-08-20 从当前模块位置解析项目根目录"""
    return _find_project_root(Path(__file__).resolve().parent)


def resolve_model_dir(run_id: str) -> Path:
    """2026-08-20 解析指定 run 的主题模型目录"""
    if not run_id or run_id in {".", ".."} or Path(run_id).name != run_id:
        raise ValueError(f"非法 run_id，无法解析主题模型目录: {run_id!r}")
    return resolve_project_root() / "models" / "topic" / run_id
