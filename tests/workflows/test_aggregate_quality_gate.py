"""
聚合质量门测试（2026-08-14 M8b 段落化重写）

chunk_style 链下线后，imagery 完整性按章节从段落指标充分统计量聚合判定：
章 token 为 0 视为缺失（不通过），零命中的章不算质量错误（§15.5）。
zero 密度口径质量门（_build_lexical_curve_quality_report）按 §15.5 移除。
"""

import uuid

import pytest

from src.metrics.aggregate import AggregateResult
from src.storage.repositories import RunRepository
from src.workflows.aggregate import _build_quality_gate_report
from tests.support.analysis_factories import insert_test_novel


def _create_run_with_paragraph_metrics(
    db_session,
    *,
    token_counts: list[int],
) -> str:
    """构造带段落指标数据的 run（每章一段；token_counts 控制各章 token 数）。"""
    from dataclasses import replace

    from src.chunking.chunker import Chunk, split_chunk_paragraphs
    from src.storage.repositories import ChunkRepository
    from src.storage.repositories.paragraph_repository import (
        ParagraphMetricRow,
        ParagraphRepository,
    )

    novel_id = uuid.uuid4().hex[:8]
    insert_test_novel(novel_id, session=db_session)
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id, source_path="test", title="Quality Gate"
    )

    texts = [f"第{i}章测试文本。" for i in range(len(token_counts))]
    chunks: list[Chunk] = []
    offset = 0
    for i, text in enumerate(texts):
        chunks.append(Chunk(index=i, start=offset, end=offset + len(text), text=text, chapter_id=i + 1))
        offset += len(text)
    ChunkRepository(db_session).insert_chunks(run_id, chunks)

    spans = [
        replace(span, token_count=1)
        for span in split_chunk_paragraphs(chunks, max_chars=1500)
    ]
    metric_rows = [
        ParagraphMetricRow(
            paragraph_id=span.paragraph_id,
            token_count=token_counts[index],
            char_count=span.char_count,
            sentence_count=1,
            sentence_char_sum=10.0,
            sentence_char_sum_sq=100.0,
            positive_weight_sum=0.0,
            negative_weight_sum=0.0,
            fight_weight_sum=0.0,
            exclaim_count=0,
            question_count=0,
            pause_count=0,
            dialogue_char_count=0,
            sensory_hit_count=0,
            imagery_hit_count=0,
            metaphor_sentence_count=0,
            function_word_counts={},
            semantic_category_counts={},
        )
        for index, span in enumerate(spans)
    ]
    paragraph_repo = ParagraphRepository(db_session)
    paragraph_repo.insert_paragraphs(run_id, spans)
    paragraph_repo.insert_paragraph_metrics(run_id, metric_rows)
    db_session.commit()
    return run_id


def test_build_quality_gate_report_flags_null_chunk_cultures(db_session) -> None:
    """token 为 0 的章（无有效密度）视为 imagery 缺失"""
    run_id = _create_run_with_paragraph_metrics(db_session, token_counts=[0, 10])
    agg_result = AggregateResult(
        language_style={"tone_distribution": {"neutral": 1.0}},
        traditional_culture={"imagery_density": 0.2},
    )

    report = _build_quality_gate_report(run_id, agg_result, db_session)

    assert report["tone_distribution_non_empty_rate"] == 1.0
    assert report["imagery_density_non_null_rate"] == 1.0
    assert report["imagery_lexicon_null_chunk_ratio"] == pytest.approx(0.5)
    assert report["imagery_lexicon_null_chunk_ids"] == [0]


def test_build_quality_gate_report_does_not_flag_zero_density_chunks(db_session) -> None:
    """零命中的章属于有效观测，不算质量错误（§15.5）"""
    run_id = _create_run_with_paragraph_metrics(db_session, token_counts=[10, 10])
    agg_result = AggregateResult(
        language_style={"tone_distribution": {"neutral": 1.0}},
        traditional_culture={"imagery_density": 0.2},
    )

    report = _build_quality_gate_report(run_id, agg_result, db_session)

    assert report["imagery_lexicon_null_chunk_ratio"] == 0.0
    assert report["imagery_lexicon_null_chunk_ids"] == []


def test_build_quality_gate_report_no_rows_is_not_a_pass(db_session) -> None:
    """2026-08-13 P2-3 无段落指标数据时质量门不通过（保守：缺数据=缺陷）"""
    novel_id = uuid.uuid4().hex[:8]
    insert_test_novel(novel_id, session=db_session)
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id, source_path="test", title="Quality Gate"
    )
    agg_result = AggregateResult(
        language_style={"tone_distribution": {"neutral": 1.0}},
        traditional_culture={"imagery_density": 0.2},
    )

    report = _build_quality_gate_report(run_id, agg_result, db_session)

    assert report["imagery_lexicon_null_chunk_ratio"] == 1.0
    assert report["imagery_lexicon_null_chunk_ids"] == []


def test_build_quality_gate_report_handles_missing_fields(db_session) -> None:
    novel_id = uuid.uuid4().hex[:8]
    insert_test_novel(novel_id, session=db_session)
    run_id = RunRepository(db_session).create_run(
        novel_id=novel_id, source_path="test", title="Quality Gate"
    )
    agg_result = AggregateResult(language_style={}, traditional_culture={})

    report = _build_quality_gate_report(run_id, agg_result, db_session)

    assert report["tone_distribution_non_empty_rate"] == 0.0
    assert report["imagery_density_non_null_rate"] == 0.0
    # 2026-08-13 P2-3 无 imagery 数据按"不通过"处理（保守）：0/0 不等于达标
    assert report["imagery_lexicon_null_chunk_ratio"] == 1.0
    assert report["imagery_lexicon_null_chunk_ids"] == []
