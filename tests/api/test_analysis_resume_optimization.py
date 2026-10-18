"""重分析恢复复用已完成阶段，新任务仍遵循 force 范围"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import settings
from src.workflows.schemas import ReanalyzeRequest
from src.workflows.service import TASK_KIND_REANALYSIS, AnalysisService
from tests.support.storage_fixtures import fixture_id, storage_factory


@pytest.mark.asyncio
@pytest.mark.parametrize("resume", [False, True])
async def test_force_is_applied_once_per_task_and_completion_chain_is_reused_on_resume(resume: bool) -> None:
    service = AnalysisService(MagicMock(), MagicMock(), session_factory=storage_factory(MagicMock()))
    service._run_analysis_core = AsyncMock()
    complete = {
        "skip_preprocess": True,
        "skip_annotate": True,
        "skip_linguistic": True,
        "skip_aggregate": True,
        "skip_topic_model": True,
        "skip_diagnose": False,
    }
    service.env_initializer.check_stage_completion_status = MagicMock(return_value=complete)
    request = ReanalyzeRequest(
        force_preprocess=True,
        force_annotate=True,
        force_linguistic=True,
        force_aggregate=True,
        force_topic_model=True,
        force_diagnose=True,
        num_topics=7,
    )
    original = request.model_dump()
    service._schedule_task_execution("task", {"novel_id": "novel"}, TASK_KIND_REANALYSIS, request, resume=resume)
    task = service.task_manager.store_asyncio_task.call_args.args[1]
    await task
    kwargs = service._run_analysis_core.call_args.kwargs
    builder = kwargs["skip_stages_builder"]
    result = builder(MagicMock(), fixture_id(__name__, "run"))

    assert kwargs["num_topics"] == 7
    assert request.model_dump() == original
    if resume:
        assert result == complete
        assert not result["skip_diagnose"]
    else:
        assert not any(result.values())
        service.env_initializer.check_stage_completion_status.assert_not_called()


def test_partial_upstream_stage_prevents_reusing_downstream_results(monkeypatch) -> None:
    from src.workflows.analysis import environment_initializer as module

    service = AnalysisService(MagicMock(), MagicMock(), session_factory=storage_factory(MagicMock()))
    monkeypatch.setattr(settings.linguistic.ltp, "enabled", True)
    queries = {
        name: MagicMock(return_value=value)
        for name, value in {
            "is_preprocess_complete": True,
            "is_annotate_complete": True,
            "is_linguistic_complete": False,
            "is_aggregate_complete": True,
            "is_topic_model_complete": True,
            "has_diagnosis_data": True,
        }.items()
    }
    for name, query in queries.items():
        monkeypatch.setattr(module, name, query)
    result = service.env_initializer.check_stage_completion_status(MagicMock(), fixture_id(__name__, "run"))
    assert result["skip_preprocess"] and result["skip_annotate"]
    assert not any(result[key] for key in ("skip_linguistic", "skip_aggregate", "skip_topic_model", "skip_diagnose"))
    queries["is_linguistic_complete"].assert_called_once()
    for name in ("is_aggregate_complete", "is_topic_model_complete", "has_diagnosis_data"):
        queries[name].assert_not_called()
