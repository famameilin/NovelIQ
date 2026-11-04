"只读接口的同步计算不阻塞其他请求"

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import get_db_session, get_metrics_service, get_novel_service, resolve_run_id
from src.api.routes import novels, tabs


def test_slow_dashboard_allows_novel_request_to_finish(monkeypatch):
    started, release = Event(), Event()

    def slow_dashboard(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return {"run_id": "run"}

    monkeypatch.setattr(tabs, "build_dashboard_tab", slow_dashboard)
    monkeypatch.setattr(tabs, "_require_run_for_novel", lambda *args: {"status": "completed"})
    app = FastAPI()
    app.include_router(tabs.router)
    app.include_router(novels.router)
    app.dependency_overrides[get_db_session] = lambda: object()
    app.dependency_overrides[get_metrics_service] = lambda: object()
    app.dependency_overrides[resolve_run_id] = lambda: "run"
    app.dependency_overrides[get_novel_service] = lambda: SimpleNamespace(get_novel=lambda novel: {"novel_id": novel})
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        slow = pool.submit(client.get, "/novels/novel/tabs/dashboard?task_id=task")
        assert started.wait(3)
        try:
            fast = pool.submit(client.get, "/novels/novel")
            assert fast.result(timeout=2).json() == {"novel_id": "novel"}
            assert not slow.done()
        finally:
            release.set()
        assert slow.result(timeout=3).status_code == 200
