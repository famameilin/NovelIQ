"""
§19.14 修复测试（2026-08-14 M8b 段落化重写）

- §19.14: emotion_peak/min_chunk_id 并列极值取最后出现的段落（rindex）；
  tension 侧对称输出 rhythm_max_chunk / rhythm_min_chunk
- 2026-08-14 重命名（§13.3）：emotion_max_chunk → emotion_peak_chunk_id，
  emotion_min_chunk → emotion_min_chunk_id
- M8b：compute_global_stats 数据源从 chunk_style/chunk_curves 改为段落事实源
  （paragraphs + paragraph_metrics + paragraph_curves），极值定位取极值段落
  所在 chunk_id
"""

from __future__ import annotations

import uuid

from src.storage.repositories import ChapterRepository, RunRepository
from src.storage.repositories.paragraph_repository import (
    ParagraphCurveRow,
    ParagraphMetricRow,
    ParagraphRepository,
)
from src.workflows.curve_metrics import compute_global_stats
from tests.support.analysis_factories import insert_test_novel


def _insert_paragraph_curves(
    db_session,
    *,
    net_densities: list[float | None],
    surface_tensions: list[float | None],
) -> str:
    """构造 4 章 4 段的 run（chapter_id = 1..4），写入段落曲线与基础指标。"""
    from dataclasses import replace

    from src.chunking.chunker import Chunk, split_chunk_paragraphs

    novel_id = uuid.uuid4().hex[:8]
    insert_test_novel(novel_id, session=db_session)
    run_id = RunRepository(db_session).create_run(novel_id=novel_id, source_path="test", title="Global Stats")

    texts = ["甲。", "乙。", "丙。", "丁。"]
    chunks: list[Chunk] = []
    offset = 0
    for i, text in enumerate(texts):
        chunks.append(Chunk(index=10 + i, start=offset, end=offset + len(text), text=text, chapter_id=1 + i))
        offset += len(text)
    ChapterRepository(db_session).insert_chapter_texts(run_id, chunks)

    spans = [replace(span, token_count=2) for span in split_chunk_paragraphs(chunks, max_chars=1500)]
    assert len(spans) == 4
    paragraph_repo = ParagraphRepository(db_session)
    paragraph_repo.insert_paragraphs(run_id, spans)

    metric_rows = [
        ParagraphMetricRow(
            paragraph_id=span.paragraph_id,
            token_count=2,
            char_count=span.char_count,
            sentence_count=1,
            sentence_char_sum=2.0,
            sentence_char_sum_sq=4.0,
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
        for span in spans
    ]
    paragraph_repo.insert_paragraph_metrics(run_id, metric_rows)

    curve_rows = [
        ParagraphCurveRow(
            paragraph_id=span.paragraph_id,
            pos_density=0.0,
            neg_density=0.0,
            net_density=net_densities[index],
            smoothed_net_density=net_densities[index],
            surface_tension=surface_tensions[index],
            smoothed_surface_tension=surface_tensions[index],
        )
        for index, span in enumerate(spans)
    ]
    paragraph_repo.insert_paragraph_curves(run_id, curve_rows)
    db_session.commit()
    return run_id


class TestGlobalStatsExtremes:
    """§19.14：并列极值取最后出现的段落（rindex）+ tension 侧对称输出"""

    def test_emotion_extremes_use_last_occurrence(self, db_session) -> None:
        # max 并列于段落 1、2 → 取段落 2（chapter_id=3）
        run_id = _insert_paragraph_curves(
            db_session,
            net_densities=[1.0, 5.0, 5.0, 2.0],
            surface_tensions=[None, None, None, None],
        )

        stats = dict(compute_global_stats(db_session, run_id))

        assert stats["emotion_max"] == 5.0
        # 2026-08-14 重命名（§13.3）：emotion_max_chunk → emotion_peak_chapter_id
        assert stats["emotion_peak_chapter_id"] == 3.0
        assert stats["emotion_min_chapter_id"] == 1.0

    def test_emotion_min_uses_last_occurrence(self, db_session) -> None:
        # min 并列于段落 0、1 → 取段落 1（chapter_id=2）
        run_id = _insert_paragraph_curves(
            db_session,
            net_densities=[0.0, 0.0, 3.0, 3.0],
            surface_tensions=[None, None, None, None],
        )

        stats = dict(compute_global_stats(db_session, run_id))

        assert stats["emotion_min"] == 0.0
        assert stats["emotion_min_chapter_id"] == 2.0
        assert stats["emotion_peak_chapter_id"] == 4.0

    def test_rhythm_extremes_symmetric_output(self, db_session) -> None:
        """§19.14 不对称修复：tension 侧新增 rhythm_peak_chapter_id/rhythm_min_chapter_id"""
        run_id = _insert_paragraph_curves(
            db_session,
            net_densities=[None, None, None, None],
            surface_tensions=[2.0, 2.0, 4.0, 4.0],
        )

        stats = dict(compute_global_stats(db_session, run_id))

        assert stats["rhythm_max"] == 4.0
        assert stats["rhythm_peak_chapter_id"] == 4.0
        assert stats["rhythm_min"] == 2.0
        assert stats["rhythm_min_chapter_id"] == 2.0

    def test_rhythm_extremes_guarded_when_no_curve_rows(self, db_session) -> None:
        """无段落曲线数据时输出张力分布统计，也不伪造极值定位"""
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        run_id = RunRepository(db_session).create_run(novel_id=novel_id, source_path="test", title="Global Stats")

        stats = dict(compute_global_stats(db_session, run_id))

        assert "rhythm_max" not in stats
        assert "rhythm_peak_chapter_id" not in stats

    def test_emotion_extremes_skip_null_density_rows(self, db_session) -> None:
        """2026-08-15 M1 回归：NULL 密度行（0-token 段）不参与极值，但下标不得错位"""
        # 4 行：第 2 行 net_density=None；峰值在段落 2（chapter_id=3）
        run_id = _insert_paragraph_curves(
            db_session,
            net_densities=[3.0, None, 5.0, 1.0],
            surface_tensions=[None, None, None, None],
        )

        stats = dict(compute_global_stats(db_session, run_id))

        assert stats["emotion_max"] == 5.0
        assert stats["emotion_peak_chapter_id"] == 3.0
        assert stats["emotion_min"] == 1.0
        assert stats["emotion_min_chapter_id"] == 4.0

    def test_rhythm_extremes_skip_null_tension_rows(self, db_session) -> None:
        """2026-08-15 M1 回归：NULL 张力行不参与极值，下标映射回未过滤 rows"""
        # 第 2 行 surface_tension=None；min 并列于段落 2、3 → 取最后（chapter_id=4）
        run_id = _insert_paragraph_curves(
            db_session,
            net_densities=[None, None, None, None],
            surface_tensions=[4.0, None, 2.0, 2.0],
        )

        stats = dict(compute_global_stats(db_session, run_id))

        assert stats["rhythm_max"] == 4.0
        assert stats["rhythm_peak_chapter_id"] == 1.0
        assert stats["rhythm_min"] == 2.0
        assert stats["rhythm_min_chapter_id"] == 4.0
