"""
GET /{novel_id}/chapter-metrics 端点测试（设计文档《章节粒度分析指标重设计》§13.2）

覆盖：
- 分子/分母聚合守恒（章节密度 = 段落分子和/分母和，非段落均值）
- 句长均值/方差从充分统计量恢复
- 章节 TTR/MTLD 与直接对章节文本计算一致
- 章节 Agent 标签映射（无标注章节为 None）
- 全书聚合字段与版本字段
- 旧 run（analysis_contract_version=NULL）409
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.config import settings
from src.metrics.style_metrics import mtld as mtld_fn
from src.metrics.style_metrics import ttr as ttr_fn
from src.preprocess.tokenize import tokenize
from tests.support.paragraph_fixtures import (
    create_completed_run,
    insert_chapter_annotation,
    insert_metrics,
    insert_spans,
    make_metric_row,
    make_span,
)

# 章节 1（chunk 0）：段落 0 + 段落 1
# 段落 0："他怒喝一声！"  pos=2.0 neg=0 fight=1.0 exclaim=1 句长充分统计量 (1, 4.0, 16.0)
# 段落 1："你为何如此？"  neg=1.0 question=1 pause=1 dialogue=6 句长充分统计量 (1, 8.0, 64.0)
# → 章节 1：tokens=10 chars=12 pos=2.0 neg=1.0 net=1.0 fight=1.0
#   exclaim/question/pause 各 1；dialogue=6；sentences=2 sum=12 sum_sq=80
#   avg_sent_len=6.0，var = 80/2 - 36 = 4 → std=2.0
#
# 章节 2（chunk 1）段落 2："平静地叙述日常。" pos=0.5 neg=0.5 tokens=7 chars=8
# → 章节 2：pos=0.5 neg=0.5 net=0.0 fight=0
#
# 章节 3（chunk 2）段落 3："此人竟敢叛变！？" neg=2.0 fight=1.0 exclaim=1 question=1
#   tokens=6 chars=8
# → 章节 3：pos=0.0 neg=2.0 net=-2.0 fight=1.0
#
# 全书：tokens=23 chars=28 pos=2.5 neg=3.5 net=-1.0 fight=2.0
#   exclaim=2 question=2 pause=1 dialogue=6 sentences=4 sum=28 sum_sq=208
#   avg_sent_len=7.0，var = 208/4 - 49 = 3 → std=sqrt(3)


def _insert_three_chapter_run(db_session, *, annotated: bool = True) -> tuple[str, str]:
    novel_id, run_id = create_completed_run(
        db_session,
        chapter_texts=[
            "他怒喝一声！\n你为何如此？",
            "平静地叙述日常。",
            "此人竟敢叛变！？",
        ],
    )
    spans = [
        make_span(
            paragraph_id=0, chapter_id=1, paragraph_index=0,
            text="他怒喝一声！", local_start=0, chunk_offset=0, token_count=5,
        ),
        make_span(
            paragraph_id=1, chapter_id=1, paragraph_index=1,
            text="你为何如此？", local_start=6, chunk_offset=0, token_count=5,
        ),
        make_span(
            paragraph_id=2, chapter_id=2, paragraph_index=0,
            text="平静地叙述日常。", local_start=0, chunk_offset=13, token_count=7,
        ),
        make_span(
            paragraph_id=3, chapter_id=3, paragraph_index=0,
            text="此人竟敢叛变！？", local_start=0, chunk_offset=21, token_count=6,
        ),
    ]
    insert_spans(db_session, run_id, spans)
    insert_metrics(
        db_session,
        run_id,
        [
            make_metric_row(
                0, token_count=5, char_count=6,
                sentence_count=1, sentence_char_sum=4.0, sentence_char_sum_sq=16.0,
                positive_weight_sum=2.0, fight_weight_sum=1.0, exclaim_count=1,
            ),
            make_metric_row(
                1, token_count=5, char_count=6,
                sentence_count=1, sentence_char_sum=8.0, sentence_char_sum_sq=64.0,
                negative_weight_sum=1.0, question_count=1, pause_count=1,
                dialogue_char_count=6,
            ),
            make_metric_row(
                2, token_count=7, char_count=8,
                sentence_count=1, sentence_char_sum=8.0, sentence_char_sum_sq=64.0,
                positive_weight_sum=0.5, negative_weight_sum=0.5,
            ),
            make_metric_row(
                3, token_count=6, char_count=8,
                sentence_count=1, sentence_char_sum=8.0, sentence_char_sum_sq=64.0,
                negative_weight_sum=2.0, fight_weight_sum=1.0,
                exclaim_count=1, question_count=1,
            ),
        ],
    )
    if annotated:
        insert_chapter_annotation(
            db_session, run_id,
            chapter_id=1,
            narrative_function="转折", emotional_valence="mild_negative",
            pivot_moment=True, cliffhanger=False,
        )
        insert_chapter_annotation(
            db_session, run_id,
            chapter_id=2,
            narrative_function="铺垫", emotional_valence="neutral",
            pivot_moment=False, cliffhanger=True,
        )
        insert_chapter_annotation(
            db_session, run_id,
            chapter_id=3,
            narrative_function="冲突", emotional_valence="strong_positive",
            pivot_moment=False, cliffhanger=False,
        )
    return novel_id, run_id


def _get_chapter_metrics(api_client, novel_id: str, run_id: str):
    response = api_client.get(
        f"/api/novels/{novel_id}/chapter-metrics",
        params={"task_id": run_id[:8]},
    )
    assert response.status_code == 200
    return response.json()


def test_chapter_metrics_aggregates_conserve_numerators_and_denominators(
    api_client: TestClient, db_session
) -> None:
    novel_id, run_id = _insert_three_chapter_run(db_session)
    payload = _get_chapter_metrics(api_client, novel_id, run_id)

    chapters = payload["chapters"]
    assert [chapter["chapter_id"] for chapter in chapters] == [1, 2, 3]

    first = chapters[0]
    assert first["paragraph_count"] == 2
    assert first["total_chars"] == 12
    assert first["total_tokens"] == 10
    # 分子/分母聚合：sum(pos) / sum(tokens) = 2.0 / 10
    assert first["pos_density"] == pytest.approx(0.2)
    assert first["neg_density"] == pytest.approx(0.1)
    assert first["net_density"] == pytest.approx(0.1)
    assert first["fight_density"] == pytest.approx(0.1)
    assert first["exclaim_per_100_chars"] == pytest.approx(100.0 / 12)
    assert first["question_per_100_chars"] == pytest.approx(100.0 / 12)
    assert first["pause_per_100_chars"] == pytest.approx(100.0 / 12)
    assert first["dialogue_ratio"] == pytest.approx(6.0 / 12)

    second = chapters[1]
    assert second["paragraph_count"] == 1
    assert second["pos_density"] == pytest.approx(0.5 / 7)
    assert second["neg_density"] == pytest.approx(0.5 / 7)
    assert second["net_density"] == pytest.approx(0.0)
    # 分母 > 0 时零命中是合法观测（§15.2），返回 0.0 而非 None
    assert second["fight_density"] == pytest.approx(0.0)
    assert second["exclaim_per_100_chars"] == pytest.approx(0.0)
    assert second["dialogue_ratio"] == pytest.approx(0.0)

    third = chapters[2]
    assert third["pos_density"] == pytest.approx(0.0)
    assert third["neg_density"] == pytest.approx(2.0 / 6)
    assert third["net_density"] == pytest.approx(-2.0 / 6)
    assert third["fight_density"] == pytest.approx(1.0 / 6)


def test_chapter_metrics_sentence_length_mean_and_std_recovered_from_sufficient_stats(
    api_client: TestClient, db_session
) -> None:
    novel_id, run_id = _insert_three_chapter_run(db_session)
    payload = _get_chapter_metrics(api_client, novel_id, run_id)

    first = payload["chapters"][0]
    assert first["avg_sent_len"] == pytest.approx(6.0)
    assert first["sent_len_std"] == pytest.approx(2.0)

    second = payload["chapters"][1]
    assert second["avg_sent_len"] == pytest.approx(8.0)
    assert second["sent_len_std"] == pytest.approx(0.0)

    book = payload["book"]
    assert book["avg_sent_len"] == pytest.approx(7.0)
    assert book["sent_len_std"] == pytest.approx(math.sqrt(3.0))


def test_chapter_metrics_ttr_mtld_match_direct_computation(
    api_client: TestClient, db_session
) -> None:
    novel_id, run_id = _insert_three_chapter_run(db_session)
    payload = _get_chapter_metrics(api_client, novel_id, run_id)

    chapters = payload["chapters"]

    chapter_texts = [
        "他怒喝一声！你为何如此？",
        "平静地叙述日常。",
        "此人竟敢叛变！？",
    ]
    for chapter, chapter_text in zip(chapters, chapter_texts, strict=True):
        tokens = tokenize(chapter_text)
        assert chapter["ttr"] == pytest.approx(ttr_fn(tokens))
        assert chapter["mtld"] == mtld_fn(tokens)

    book_text = "".join(chapter_texts)
    book_tokens = tokenize(book_text)
    book = payload["book"]
    assert book["ttr"] == pytest.approx(ttr_fn(book_tokens))
    assert book["mtld"] == mtld_fn(book_tokens)


def test_chapter_metrics_annotation_labels_mapped_per_chapter(
    api_client: TestClient, db_session
) -> None:
    novel_id, run_id = _insert_three_chapter_run(db_session)
    payload = _get_chapter_metrics(api_client, novel_id, run_id)

    chapters = {chapter["chapter_id"]: chapter for chapter in payload["chapters"]}
    assert chapters[1]["narrative_function"] == "转折"
    assert chapters[1]["pivot_moment"] is True
    assert chapters[1]["cliffhanger"] is False
    assert chapters[1]["emotional_valence"] == "mild_negative"

    assert chapters[2]["narrative_function"] == "铺垫"
    assert chapters[2]["pivot_moment"] is False
    assert chapters[2]["cliffhanger"] is True

    assert chapters[3]["narrative_function"] == "冲突"
    assert chapters[3]["emotional_valence"] == "strong_positive"


def test_chapter_metrics_without_annotations_returns_none_labels(
    api_client: TestClient, db_session
) -> None:
    novel_id, run_id = _insert_three_chapter_run(db_session, annotated=False)
    payload = _get_chapter_metrics(api_client, novel_id, run_id)

    for chapter in payload["chapters"]:
        assert chapter["narrative_function"] is None
        assert chapter["pivot_moment"] is None
        assert chapter["cliffhanger"] is None
        assert chapter["emotional_valence"] is None

    book = payload["book"]
    assert book["chapter_narrative_function_share"] == {}
    assert book["chapter_emotional_valence_share"] == {}
    assert book["chapter_pivot_rate"] is None
    assert book["chapter_cliffhanger_rate"] is None


def test_chapter_metrics_book_aggregate_and_version_fields(
    api_client: TestClient, db_session
) -> None:
    novel_id, run_id = _insert_three_chapter_run(db_session)
    payload = _get_chapter_metrics(api_client, novel_id, run_id)

    book = payload["book"]
    assert book["total_chapters"] == 3
    assert book["total_paragraphs"] == 4
    assert book["total_chars"] == 28
    assert book["total_tokens"] == 23
    assert book["pos_density"] == pytest.approx(2.5 / 23)
    assert book["neg_density"] == pytest.approx(3.5 / 23)
    assert book["net_density"] == pytest.approx(-1.0 / 23)
    assert book["fight_density"] == pytest.approx(2.0 / 23)
    assert book["exclaim_per_100_chars"] == pytest.approx(200.0 / 28)
    assert book["question_per_100_chars"] == pytest.approx(200.0 / 28)
    assert book["pause_per_100_chars"] == pytest.approx(100.0 / 28)
    assert book["dialogue_ratio"] == pytest.approx(6.0 / 28)

    assert book["chapter_narrative_function_share"] == {
        "转折": pytest.approx(1.0 / 3),
        "铺垫": pytest.approx(1.0 / 3),
        "冲突": pytest.approx(1.0 / 3),
    }
    assert book["chapter_emotional_valence_share"] == {
        "mild_negative": pytest.approx(1.0 / 3),
        "neutral": pytest.approx(1.0 / 3),
        "strong_positive": pytest.approx(1.0 / 3),
    }
    assert book["chapter_pivot_rate"] == pytest.approx(1.0 / 3)
    assert book["chapter_cliffhanger_rate"] == pytest.approx(1.0 / 3)

    assert book["analysis_contract_version"] == "paragraph-v1"
    assert book["paragraph_splitter_version"] == settings.paragraphs.splitter_version
    assert book["metric_version"] == settings.metrics.metric_version
    assert book["curve_version"] == settings.metrics.curve_version


def test_chapter_metrics_requires_paragraph_contract(api_client: TestClient, db_session) -> None:
    novel_id, run_id = create_completed_run(db_session, chapter_texts=["第一段。"])

    db_session.execute(
        text("UPDATE analysis_runs SET analysis_contract_version = NULL WHERE run_id = :run_id"),
        {"run_id": run_id},
    )
    db_session.commit()

    response = api_client.get(
        f"/api/novels/{novel_id}/chapter-metrics",
        params={"task_id": run_id[:8]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "paragraph_contract_rerun_required"
