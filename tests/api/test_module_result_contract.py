"""模块重构前后固定数据的完整结果契约回归"""

from __future__ import annotations

import json
from pathlib import Path

from tests.support.result_contract_snapshot import capture, differences, normalize, prepare_scenario


def test_fixed_results_match_declaration_contract(api_client, db_session, monkeypatch) -> None:
    scenario = prepare_scenario(db_session, monkeypatch)
    actual = normalize(capture(api_client, scenario.novel_id, scenario.task_id))
    baseline = json.loads((Path(__file__).parent / "fixtures/module_results_baseline.json").read_text(encoding="utf-8"))
    assert baseline["baseline_contract_version"] == "event-tree-declarations-v1"
    events = actual["event-trees"]
    assert events["counts"]["all_events"] == 9 and events["counts"]["declarations"] == 10
    assert next(item for item in events["events"] if item["title"] == "踏入江湖")["status"] == "resolved"
    exported = actual["export"]["event_trees"]
    assert len(exported["declaration_bindings"]) == 10 and len(exported["revisions"]) == 10
    assert "processes" not in exported and "process_structures" not in exported
    changed = differences(baseline["responses"], actual)
    assert not changed, "\n".join(changed)
