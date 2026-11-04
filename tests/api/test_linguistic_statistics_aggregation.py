"""正式语言统计的完整响应对照与聚合边界"""

import json
from pathlib import Path

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from src.storage.repositories.linguistic_repository import LinguisticRepository
from tests.support.linguistic_fixtures import generated_linguistic_row
from tests.support.paragraph_fixtures import create_completed_run, insert_spans, make_span
from tests.support.storage_fixtures import task_for_run


def _row(paragraph_id, words, sdp):
    tokens = []
    cursor = 0
    for index, word in enumerate(words, 1):
        tokens.append({
            "token_index": index, "text": word, "local_start_char": cursor,
            "local_end_char": cursor + len(word), "pos_tag": "n" if index == 1 else "v",
        })
        cursor += len(word)
    return generated_linguistic_row("".join(words), {
        "paragraph_id": paragraph_id, "tokens": tokens, "sentence_count": 1,
        "sentence_pattern_counts": {"short": 1},
        "dependency_arcs": [
            {"dependent_index": index, "head_index": 0 if index == 1 else 1, "relation": "HED" if index == 1 else "ATT"}
            for index in range(1, len(words) + 1)
        ],
        "sdp_arcs": sdp,
    })


def _seed(session):
    words = ["阿青", "不", "太", "高兴", "，", "但", "阿白", "高兴", "。"]
    first = "".join(words)
    second = "伤心。"
    novel_id, run_id = create_completed_run(session, chapter_texts=[first + "\n" + second, "。"])
    insert_spans(session, run_id, [
        make_span(paragraph_id=0, chapter_id=1, paragraph_index=0, text=first, local_start=0, chunk_offset=0),
        make_span(paragraph_id=1, chapter_id=1, paragraph_index=1, text=second,
                  local_start=len(first) + 1, chunk_offset=0),
        make_span(paragraph_id=2, chapter_id=2, paragraph_index=0, text="。", local_start=0,
                  chunk_offset=len(first) + len(second) + 1),
    ])
    rows = [
        _row(0, words, [
            {"head_index": 4, "dependent_index": 1, "label": "AGT"},
            {"head_index": 4, "dependent_index": 2, "label": "mNEG"},
            {"head_index": 4, "dependent_index": 3, "label": "mDEPD"},
            {"head_index": 8, "dependent_index": 7, "label": "AGT"},
        ]),
        _row(1, ["伤心", "。"], []),
        generated_linguistic_row("。", {"paragraph_id": 2, "sentence_count": 1}),
    ]
    LinguisticRepository(session).insert_linguistic_features(run_id, rows)
    session.execute(text(
        "UPDATE paragraph_metrics SET boundary_pos_score_sum = 0.1234567, boundary_neg_score_sum = 0 "
        "WHERE run_id = :run_id AND paragraph_id = 0"
    ), {"run_id": run_id})
    session.commit()
    return novel_id, run_id


def test_saved_statistics_match_complete_response_without_read_time_analysis(api_client, db_session, monkeypatch):
    novel_id, run_id = _seed(db_session)
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "linguistic_statistics_response.json"
    expected = json.loads(fixture.read_text(encoding="utf-8"))
    expected["run_id"] = run_id
    def forbidden(*args, **kwargs):
        pytest.fail("聚合请求不得读取底层结构或重新分析")

    monkeypatch.setattr(LinguisticRepository, "fetch_linguistic_sources", forbidden)
    monkeypatch.setattr("src.linguistic.statistics.build_paragraph_statistics", forbidden)
    monkeypatch.setattr("src.linguistic.emotion_events.extract_emotion_events", forbidden)
    monkeypatch.setattr("src.linguistic.emotion_events.mneg_corrected_counts", forbidden)
    monkeypatch.setattr("src.linguistic.ltp_client._count_dependency_statistics", forbidden)
    statements = []
    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
    event.listen(Engine, "before_cursor_execute", observe)
    try:
        response = api_client.get(
            f"/api/novels/{novel_id}/linguistic/features", params={"task_id": task_for_run(run_id, db_session)}
        )
    finally:
        event.remove(Engine, "before_cursor_execute", observe)
    assert response.status_code == 200
    assert response.json() == expected
    assert response.json()["emotion_event_count"] == 3
    assert [row["holder"] for row in response.json()["emotion_event_holders"]] == ["阿青", "阿白"]
    assert response.json()["chapters"][1]["token_total"] == 0
    assert response.json()["chapters"][1]["avg_dependency_depth"] is None
    assert not any("paragraph_arcs" in statement for statement in statements)
    assert any("grouping sets" in statement for statement in statements)


def test_emotion_holder_cannot_reference_a_token_outside_its_paragraph(db_session):
    _, run_id = _seed(db_session)
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(text(
            "UPDATE paragraph_spans SET emotion_polarity = 'positive', emotion_negated = false, "
            "emotion_holder_token_index = 8 WHERE run_id = :run_id AND paragraph_id = 1 AND token_index = 0"
        ), {"run_id": run_id})
        db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
