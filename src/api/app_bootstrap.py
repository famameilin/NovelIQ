from __future__ import annotations

from importlib import import_module

from src.config import settings as BOOTSTRAP_SETTINGS
from src.config.logging_config import setup_logging

# API 入口需要先完成配置加载和日志初始化，再导入 routes / middleware，
# 否则模块导入阶段的日志会绕过统一配置直接落到控制台
setup_logging(verbose=True, debug=False)

_middleware_module = import_module("src.api.middleware")
_routes_module = import_module("src.api.routes")
_sse_module = import_module("src.api.routes.sse")

register_exception_handlers = _middleware_module.register_exception_handlers
register_middlewares = _middleware_module.register_middlewares
analysis_router = _routes_module.analysis_router
novels_router = _routes_module.novels_router
results_router = _routes_module.results_router
timeline_router = _routes_module.timeline_router
sse_router = _sse_module.router

__all__ = [
    "BOOTSTRAP_SETTINGS",
    "analysis_router",
    "novels_router",
    "register_exception_handlers",
    "register_middlewares",
    "results_router",
    "sse_router",
    "timeline_router",
]
