"""模块重构前后固定数据的完整结果契约回归"""

from __future__ import annotations

import json
from pathlib import Path

from tests.support.result_contract_snapshot import capture, differences, normalize, prepare_scenario


def test_fixed_results_equal_pre_refactor_baseline(api_client, db_session, monkeypatch) -> None:
    scenario = prepare_scenario(db_session, monkeypatch)
    actual = normalize(capture(api_client, scenario.novel_id, scenario.task_id))
    baseline = json.loads((Path(__file__).parent / "fixtures/module_results_baseline.json").read_text(encoding="utf-8"))
    changed = differences(baseline["responses"], actual)
    assert not changed, "\n".join(changed)
