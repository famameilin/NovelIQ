"api dependencies 的具名物理读取"

from __future__ import annotations

from src.storage.models import AnalysisRun


def api_dependencies_require_run_for_novel_1(_session, run_id):
    return _session.get(AnalysisRun, run_id)
