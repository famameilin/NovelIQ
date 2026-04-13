from __future__ import annotations

__all__ = ["novels_router", "analysis_router", "results_router", "timeline_router"]


def __getattr__(name: str):
    """Lazily expose routers without forcing package-wide route imports."""

    if name == "analysis_router":
        from src.api.routes.analysis import router as analysis_router

        return analysis_router
    if name == "novels_router":
        from src.api.routes.novels import router as novels_router

        return novels_router
    if name == "results_router":
        from src.api.routes.results import router as results_router

        return results_router
    if name == "timeline_router":
        from src.api.routes.timeline import router as timeline_router

        return timeline_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
