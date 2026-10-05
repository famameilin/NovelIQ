"""发布边界保留连续性事实，不生成质量报告或提供人工复核入口"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.main import app
from src.storage.db import get_session_factory
from src.storage.models import AnalysisCutoff, AnalysisRun, Base
from src.storage.repositories.pipeline_projection import PipelineProjectionRepository
from tests.storage.test_pipeline_continuity_projection import _source


def test_pipeline_review_route_is_not_registered() -> None:
    paths = app.openapi()["paths"]
    assert "/api/novels/{novel_id}/pipeline" in paths
    assert "/api/novels/{novel_id}/pipeline/reviews" not in paths
    assert "pipeline_quality_reviews" not in Base.metadata.tables


def test_pipeline_review_request_returns_not_found(api_client: TestClient) -> None:
    response = api_client.post("/api/novels/missing/pipeline/reviews", json={})
    assert response.status_code == 404


@pytest.mark.usefixtures("pipeline_run_cleanup")
def test_pipeline_snapshot_has_no_quality_monitoring(db_session: Session, api_client: TestClient) -> None:
    run_id, _, _ = _source(db_session)
    factory = get_session_factory()
    boundary = PipelineProjectionRepository(factory).latest_released(run_id)
    assert boundary is not None
    assert "quality" not in boundary["manifest"]
    with factory() as session, session.begin():
        run = session.get(AnalysisRun, run_id)
        cutoff = session.get(AnalysisCutoff, boundary["cutoff_hash"])
        assert run is not None and cutoff is not None
        run.annotation_cutoff_hash = cutoff.cutoff_hash
        novel_id = run.novel_id

    response = api_client.get(f"/api/novels/{novel_id}/pipeline", params={"task_id": run_id[:8]})
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["cutoff_hash"] == boundary["cutoff_hash"]
    assert snapshot["formal_count"] == 2
    assert snapshot["case_states"]["pending"] == 1
    assert "quality" not in snapshot and "quality_reviews" not in snapshot
