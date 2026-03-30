from __future__ import annotations

from src.api.routes.analysis import router as analysis_router
from src.api.routes.novels import router as novels_router
from src.api.routes.results import router as results_router
from src.api.routes.timeline import router as timeline_router

__all__ = ["novels_router", "analysis_router", "results_router", "timeline_router"]
