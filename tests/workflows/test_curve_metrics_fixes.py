"""
§19.6 与 §19.14 修复测试

- §19.6: tension_proxy 各分量先 clip 到 [0,1] 再等权平均（_proxy_score）
- §19.14: emotion_max/min_chunk 并列极值取最后出现的索引（rindex）；
  tension 侧对称输出 rhythm_max_chunk / rhythm_min_chunk
"""

from __future__ import annotations

import pytest

from src.workflows.curve_metrics import (
    _proxy_score,
    compute_global_stats,
    compute_rhythm_curve,
)


class TestProxyScore:
    """§19.6：量纲统一后再等权平均"""

    def test_empty_proxy_returns_zero(self) -> None:
        assert _proxy_score({}) == 0.0

    def test_densities_are_clipped_to_unit_range(self) -> None:
        proxy = {
            "fight_density": 2.0,
            "exclaim_density": 0.5,
            "question_density": 0.0,
            "dialogue_ratio": 1.0,
            "avg_sent_len": 25.0,
        }
        # clip 后: 1.0, 0.5, 0.0, 1.0, min(25/50,1)=0.5 → 3.0/5
        assert _proxy_score(proxy) == pytest.approx(0.6)

    def test_avg_sent_len_capped_at_50(self) -> None:
        proxy = {
            "fight_density": 0.0,
            "exclaim_density": 0.0,
            "question_density": 0.0,
            "dialogue_ratio": 0.0,
            "avg_sent_len": 200.0,
        }
        # min(200/50, 1) = 1.0 → 1.0/5
        assert _proxy_score(proxy) == pytest.approx(0.2)

    def test_sent_len_no_longer_dominates(self) -> None:
        """
        修复前 avg_sent_len 量纲远大于密度，会主导结果（如 100 字句长
        把等权均值抬到 20+）；修复后两种文本的 proxy 分数都在 [0,1] 内
        且差距大幅缩小
        """
        short = {
            "fight_density": 0.1,
            "exclaim_density": 0.1,
            "question_density": 0.1,
            "dialogue_ratio": 0.1,
            "avg_sent_len": 10.0,
        }
        long = {
            "fight_density": 0.1,
            "exclaim_density": 0.1,
            "question_density": 0.1,
            "dialogue_ratio": 0.1,
            "avg_sent_len": 100.0,
        }
        assert _proxy_score(short) == pytest.approx(0.12)
        assert _proxy_score(long) == pytest.approx(0.28)
        assert 0.0 <= _proxy_score(long) <= 1.0


class TestRhythmCurveProxyScore:
    """§19.6 集成：compute_rhythm_curve 使用 _proxy_score"""

    def test_rhythm_curve_proxy_score_in_unit_range(self) -> None:
        # 战斗密度可 >1（多次命中），avg_sent_len 可远大于密度量纲
        rows = compute_rhythm_curve(
            [(0, "刀光剑影！刀光剑影！" * 10), (1, "平静的叙述")],
            fight_terms={"刀光": 1.0, "剑影": 1.0},
            tension_composite_values=[0.5, 0.5],
        )
        assert len(rows) == 2
        for _chunk_id, proxy_score, _composite in rows:
            assert 0.0 <= proxy_score <= 1.0


class TestGlobalStatsExtremes:
    """§19.14：并列极值取最后出现的索引 + tension 侧对称输出"""

    def test_emotion_extremes_use_last_occurrence(self, db_session) -> None:
        raw_densities = [1.0, 5.0, 5.0, 2.0]  # max 并列于 1、2 → 取 2
        chunk_texts = [(10, "a"), (11, "b"), (12, "c"), (13, "d")]

        stats = dict(
            compute_global_stats(db_session, "run-x", raw_densities, [], chunk_texts)
        )

        assert stats["emotion_max"] == 5.0
        assert stats["emotion_max_chunk"] == 12.0
        assert stats["emotion_min_chunk"] == 10.0

    def test_emotion_min_uses_last_occurrence(self, db_session) -> None:
        raw_densities = [0.0, 0.0, 3.0, 3.0]  # min 并列于 0、1 → 取 1
        chunk_texts = [(10, "a"), (11, "b"), (12, "c"), (13, "d")]

        stats = dict(
            compute_global_stats(db_session, "run-x", raw_densities, [], chunk_texts)
        )

        assert stats["emotion_min"] == 0.0
        assert stats["emotion_min_chunk"] == 11.0
        assert stats["emotion_max_chunk"] == 13.0

    def test_rhythm_extremes_symmetric_output(self, db_session) -> None:
        """§19.14 不对称修复：tension 侧新增 rhythm_max_chunk/rhythm_min_chunk"""
        tension_values = [2.0, 2.0, 4.0, 4.0]
        chunk_texts = [(10, "a"), (11, "b"), (12, "c"), (13, "d")]

        stats = dict(
            compute_global_stats(db_session, "run-x", [], tension_values, chunk_texts)
        )

        assert stats["rhythm_max"] == 4.0
        assert stats["rhythm_max_chunk"] == 13.0
        assert stats["rhythm_min"] == 2.0
        assert stats["rhythm_min_chunk"] == 11.0

    def test_rhythm_extremes_guarded_when_chunk_texts_absent(self, db_session) -> None:
        """tension 有值但 chunk_texts 为空时不越界崩溃，也不伪造 chunk 输出"""
        stats = dict(compute_global_stats(db_session, "run-x", [], [1.0, 2.0], []))

        assert stats["rhythm_max"] == 2.0
        assert "rhythm_max_chunk" not in stats
