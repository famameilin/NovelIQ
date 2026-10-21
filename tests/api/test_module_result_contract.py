"""模块结果契约回归：固定输入数据的完整结果契约"""

from __future__ import annotations

import json
import os
from pathlib import Path

from tests.support.result_contract_snapshot import capture, differences, normalize, prepare_scenario


def test_fixed_results_match_declaration_contract(api_client, db_session, monkeypatch) -> None:
    scenario = prepare_scenario(db_session, monkeypatch)
    actual = normalize(capture(api_client, scenario.novel_id, scenario.task_id))
    if os.environ.get("NOVELIQ_REFRESH_RESULT_FIXTURE") == "1":
        target = Path(__file__).parent / "fixtures/module_results_baseline.json"
        target.write_text(
            json.dumps(
                {
                    "normalization": [
                        "results.file_path",
                        "export.generated_at",
                        "results.missing_fields.topic_model_artifact_missing.path",
                    ],
                    "unordered_collections": ["graph.edges", "export.character_relations"],
                    "responses": actual,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    baseline = json.loads((Path(__file__).parent / "fixtures/module_results_baseline.json").read_text(encoding="utf-8"))
    events = actual["event-trees"]
    assert events["counts"]["all_events"] == 10 and "declarations" not in events["counts"]
    assert next(item for item in events["events"] if item["title"] == "踏入江湖")["status"] == "ongoing"
    exported = actual["export"]["event_trees"]
    assert "declaration_bindings" not in exported and "declarations" not in exported
    assert "processes" not in exported and "process_structures" not in exported
    changed = differences(baseline["responses"], actual)
    assert not changed, "\n".join(changed)
