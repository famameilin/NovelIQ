import json

from sqlalchemy import text

from src.models.cloud import build_diagnosis_payload


def test_build_diagnosis_payload_reads_three_layer_checkpoint(db_session):
    run_id = "run-payload-state"
    novel_id = "novel-payload-state"
    state_payload = {
        "discovered_names": ["masked_person", "bai_zhi", "monkey", "hou_fei_bai"],
        "known_canonical_names": ["bai_zhi", "hou_fei_bai"],
        "alias_merges": [
            ["masked_person", "bai_zhi"],
            ["monkey", "hou_fei_bai"],
        ],
        "review_status": [],
        "pending_relations": [],
        "version": 1,
        "created_at": 1.0,
        "updated_at": 1.0,
    }
    db_session.execute(
        text(
            """
            INSERT INTO disambig_checkpoint (run_id, state_json, updated_at)
            VALUES (:run_id, :state_json, :updated_at)
            """
        ),
        {
            "run_id": run_id,
            "state_json": json.dumps(state_payload, ensure_ascii=False),
            "updated_at": 1.0,
        },
    )
    db_session.commit()

    payload = build_diagnosis_payload(db_session, novel_id=novel_id, run_id=run_id)

    assert payload["known_characters"] == ["bai_zhi", "hou_fei_bai"]
    assert payload["alias_merges"] == {
        "masked_person": "bai_zhi",
        "monkey": "hou_fei_bai",
    }
    assert "graph_summary" in payload
    assert "graph_quality_report" in payload
    assert "quality" not in payload["graph_summary"]
