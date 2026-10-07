"""
模型路径解析

所有模型读写都通过本模块解析项目根目录，避免依赖进程当前工作目录
"""

from __future__ import annotations

from pathlib import Path

_RUN_MODEL_KINDS = frozenset({"topic", "word2vec"})


def _find_project_root(start: Path) -> Path:
    """从给定目录向上查找项目根目录；本地设置覆盖文件可以不存在。"""
    resolved_start = start.resolve()
    for candidate in (resolved_start, *resolved_start.parents):
        has_checkout_markers = (candidate / "pyproject.toml").is_file() and (candidate / "config").is_dir()
        if has_checkout_markers or (candidate / "config" / "settings.json").is_file():
            return candidate
    raise RuntimeError("无法定位项目根目录：祖先目录中未找到 pyproject.toml + config/ 或 config/settings.json")


def resolve_project_root() -> Path:
    """2026-08-20 从当前模块位置解析项目根目录"""
    return _find_project_root(Path(__file__).resolve().parent)


def resolve_run_model_dir(run_id: str, kind: str) -> Path:
    """2026-08-30 用于按受支持模型类型解析 run 私有目录并阻断路径注入"""
    if not run_id or run_id in {".", ".."} or Path(run_id).name != run_id:
        raise ValueError(f"非法 run_id，无法解析模型目录: {run_id!r}")
    if kind not in _RUN_MODEL_KINDS:
        raise ValueError(f"非法模型类型，无法解析模型目录: {kind!r}")
    return resolve_project_root() / "models" / kind / run_id


def resolve_model_dir(run_id: str) -> Path:
    """2026-08-30 用于通过统一路径契约解析指定 run 的主题模型目录"""
    return resolve_run_model_dir(run_id, "topic")
