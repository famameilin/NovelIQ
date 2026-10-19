"""曲线指标测试

- emotion_peak/min_chunk_id 并列极值取最后出现的段落（rindex）；
  tension 侧对称输出 rhythm_max_chunk / rhythm_min_chunk
- 极值定位：compute_global_stats 数据源为段落事实源
  （paragraphs + paragraph_metrics + 张力观测），取极值段落所在 chunk_id
- 净密度由指标分子÷同口径 token_count 投影，表面张力由
  paragraph_features 的 tension_z 观测按 sigmoid 投影，
  故本文件以分子/token 与 z 值构造输入，断言同一算法口径下的统计输出。
"""

from __future__ import annotations

import pytest

from src.metrics.paragraph_surface_tension import surface_tension_sigmoid
from src.metrics.queries.global_stats import query_global_stats as compute_global_stats
from src.storage import new_id
from src.storage.repositories import ChapterRepository, RunRepository
from src.storage.repositories.paragraph import insert_paragraph_tension_observations
from src.storage.repositories.paragraph_repository import (
    ParagraphMetricRow,
    ParagraphRepository,
)
from tests.support.analysis_factories import insert_test_novel
from tests.support.storage_fixtures import storage_for


def _insert_paragraph_metrics(
    db_session,
    *,
    net_densities: list[float | None],
    surface_tension_zs: list[float | None],
    positive_sums: list[float] | None = None,
) -> str:
    """构造 4 章 4 段的 run（chapter_id = 1..4），写入段落指标与张力 z 观测。

    net_densities 以 token_count=2 的分子表达（None 表示分母为 0 → 净密度 NULL）；
    surface_tension_zs 为正式 z 观测（None 表示无观测 → 张力投影 NULL）。
    """
    from dataclasses import replace

    from src.text_processing.models import Chunk
    from src.text_processing.paragraphs import split_chunk_paragraphs

    novel_id = new_id()
    insert_test_novel(novel_id, session=db_session)
    run_id = RunRepository(db_session).create_run(novel_id=novel_id)

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

    def _molecules(index: int, net_density: float | None) -> tuple[int, float, float]:
        if net_density is None:
            return 0, 0.0, 0.0
        token_count = 2
        positive = token_count * net_density if net_density > 0 else 0.0
        negative = -token_count * net_density if net_density < 0 else 0.0
        return token_count, positive, negative

    metric_rows = []
    for index, span in enumerate(spans):
        token_count, positive, negative = _molecules(index, net_densities[index])
        if positive_sums is not None:
            positive = positive_sums[index]
        metric_rows.append(
            ParagraphMetricRow(
                paragraph_id=span.paragraph_id,
                token_count=token_count,
                sentence_count=1,
                sentence_char_sum=2.0,
                sentence_char_sum_sq=4.0,
                positive_weight_sum=positive,
                negative_weight_sum=negative,
                fight_weight_sum=0.0,
                exclaim_count=0,
                question_count=0,
                pause_count=0,
                dialogue_char_count=0,
                sensory_hit_count=0,
                imagery_hit_count=0,
                metaphor_sentence_count=0,
                body_reaction_hit_count=0,
            )
        )
    paragraph_repo.insert_paragraph_metrics(run_id, metric_rows)
    # 张力 z 观测与指标行同族，经正式子表入口写入（None 不伪造观测行）
    insert_paragraph_tension_observations(
        db_session,
        run_id,
        [(span.paragraph_id, surface_tension_zs[index]) for index, span in enumerate(spans)],
    )
    db_session.commit()
    return run_id


class TestGlobalStatsExtremes:
    """并列极值取最后出现的段落（rindex）+ tension 侧对称输出"""

    def test_emotion_extremes_use_last_occurrence(self, db_session) -> None:
        # max 并列于段落 1、2 → 取段落 2（chapter_id=3）
        run_id = _insert_paragraph_metrics(
            db_session,
            net_densities=[1.0, 5.0, 5.0, 2.0],
            surface_tension_zs=[None, None, None, None],
        )

        stats = dict(compute_global_stats(storage_for(db_session), run_id))

        assert stats["emotion_max"] == 5.0
        # 极值字段：emotion_max_chunk → emotion_peak_chapter_id
        assert stats["emotion_peak_chapter_id"] == 3.0
        assert stats["emotion_min_chapter_id"] == 1.0

    def test_emotion_min_uses_last_occurrence(self, db_session) -> None:
        # min 并列于段落 0、1 → 取段落 1（chapter_id=2）
        run_id = _insert_paragraph_metrics(
            db_session,
            net_densities=[0.0, 0.0, 3.0, 3.0],
            surface_tension_zs=[None, None, None, None],
        )

        stats = dict(compute_global_stats(storage_for(db_session), run_id))

        assert stats["emotion_min"] == 0.0
        assert stats["emotion_min_chapter_id"] == 2.0
        assert stats["emotion_peak_chapter_id"] == 4.0

    def test_rhythm_extremes_symmetric_output(self, db_session) -> None:
        """不对称极值：tension 侧输出 rhythm_peak_chapter_id/rhythm_min_chapter_id"""
        run_id = _insert_paragraph_metrics(
            db_session,
            net_densities=[None, None, None, None],
            surface_tension_zs=[2.0, 2.0, 4.0, 4.0],
        )

        stats = dict(compute_global_stats(storage_for(db_session), run_id))

        # 存储 z、读取 sigmoid：极值比较仍是同一单调口径
        assert stats["rhythm_max"] == pytest.approx(surface_tension_sigmoid(4.0))
        assert stats["rhythm_peak_chapter_id"] == 4.0
        assert stats["rhythm_min"] == pytest.approx(surface_tension_sigmoid(2.0))
        assert stats["rhythm_min_chapter_id"] == 2.0

    def test_rhythm_extremes_guarded_when_no_curve_rows(self, db_session) -> None:
        """无段落曲线数据时输出张力分布统计，也不伪造极值定位"""
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = RunRepository(db_session).create_run(novel_id=novel_id)

        stats = dict(compute_global_stats(storage_for(db_session), run_id))

        assert "rhythm_max" not in stats
        assert "rhythm_peak_chapter_id" not in stats

    def test_emotion_extremes_skip_null_density_rows(self, db_session) -> None:
        """NULL 密度行（0-token 段）不参与极值，但下标不得错位"""
        # 4 行：第 2 行净密度=None；峰值在段落 2（chapter_id=3）
        run_id = _insert_paragraph_metrics(
            db_session,
            net_densities=[3.0, None, 5.0, 1.0],
            surface_tension_zs=[None, None, None, None],
        )

        stats = dict(compute_global_stats(storage_for(db_session), run_id))

        assert stats["emotion_max"] == 5.0
        assert stats["emotion_peak_chapter_id"] == 3.0
        assert stats["emotion_min"] == 1.0
        assert stats["emotion_min_chapter_id"] == 4.0

    def test_rhythm_extremes_skip_null_tension_rows(self, db_session) -> None:
        """NULL 张力行不参与极值，下标映射回未过滤 rows"""
        # 第 2 行无张力观测；min 并列于段落 2、3 → 取最后（chapter_id=4）
        run_id = _insert_paragraph_metrics(
            db_session,
            net_densities=[None, None, None, None],
            surface_tension_zs=[4.0, None, 2.0, 2.0],
        )

        stats = dict(compute_global_stats(storage_for(db_session), run_id))

        assert stats["rhythm_max"] == pytest.approx(surface_tension_sigmoid(4.0))
        assert stats["rhythm_peak_chapter_id"] == 1.0
        assert stats["rhythm_min"] == pytest.approx(surface_tension_sigmoid(2.0))
        assert stats["rhythm_min_chapter_id"] == 4.0


class TestLexiconZeroHitShare:
    """词典零信号段落字符加权占比（覆盖缺口审计口径）"""

    def test_zero_hit_share_is_char_weighted(self, db_session) -> None:
        # 4 段各 2 字符；仅首段有正向信号 → 零信号字符 6/8
        run_id = _insert_paragraph_metrics(
            db_session,
            net_densities=[1.0, 0.0, 0.0, 2.0],
            surface_tension_zs=[None, None, None, None],
            positive_sums=[4.0, 0.0, 0.0, 0.0],
        )

        stats = dict(compute_global_stats(storage_for(db_session), run_id))

        assert stats["lexicon_zero_hit_share"] == 6 / 8

    def test_all_zero_hit_when_no_signal_anywhere(self, db_session) -> None:
        run_id = _insert_paragraph_metrics(
            db_session,
            net_densities=[0.0, 0.0, 0.0, 0.0],
            surface_tension_zs=[None, None, None, None],
        )

        stats = dict(compute_global_stats(storage_for(db_session), run_id))

        assert stats["lexicon_zero_hit_share"] == 1.0

    def test_not_emitted_when_no_metric_rows(self, db_session) -> None:
        """无指标行=数据缺失，不得冒充零信号（不输出该统计）"""
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        run_id = RunRepository(db_session).create_run(novel_id=novel_id)

        stats = dict(compute_global_stats(storage_for(db_session), run_id))

        assert "lexicon_zero_hit_share" not in stats
