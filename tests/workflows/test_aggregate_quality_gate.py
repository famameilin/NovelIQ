from src.metrics.aggregate import AggregateResult
from src.workflows.aggregate import _build_lexical_curve_quality_report, _build_quality_gate_report


class _StubChunkRepo:
    def __init__(self, rows):
        self._rows = rows

    def fetch_chunk_imagery_lexicon_densities(self, run_id: str):
        return self._rows


def test_build_quality_gate_report_flags_null_chunk_cultures() -> None:
    agg_result = AggregateResult(
        language_style={"tone_distribution": {"neutral": 1.0}},
        traditional_culture={"imagery_density": 0.2},
    )
    chunk_repo = _StubChunkRepo(
        [
            (0, None),
            (1, 0.0),
        ]
    )

    report = _build_quality_gate_report("run-x", agg_result, chunk_repo)

    assert report["tone_distribution_non_empty_rate"] == 1.0
    assert report["imagery_density_non_null_rate"] == 1.0
    assert report["imagery_lexicon_null_chunk_ratio"] == 0.5
    assert report["imagery_lexicon_null_chunk_ids"] == [0]


def test_build_quality_gate_report_does_not_flag_zero_density_chunks() -> None:
    agg_result = AggregateResult(
        language_style={"tone_distribution": {"neutral": 1.0}},
        traditional_culture={"imagery_density": 0.2},
    )
    chunk_repo = _StubChunkRepo(
        [
            (0, 0.0),
            (1, 0.0),
        ]
    )

    report = _build_quality_gate_report("run-z", agg_result, chunk_repo)

    assert report["imagery_lexicon_null_chunk_ratio"] == 0.0
    assert report["imagery_lexicon_null_chunk_ids"] == []


def test_build_quality_gate_report_no_rows_is_not_a_pass() -> None:
    """2026-08-13 P2-3 无 imagery 数据行时质量门不通过（保守：缺数据=缺陷）"""
    agg_result = AggregateResult(
        language_style={"tone_distribution": {"neutral": 1.0}},
        traditional_culture={"imagery_density": 0.2},
    )
    chunk_repo = _StubChunkRepo([])

    report = _build_quality_gate_report("run-n", agg_result, chunk_repo)

    assert report["imagery_lexicon_null_chunk_ratio"] == 1.0
    assert report["imagery_lexicon_null_chunk_ids"] == []


def test_build_quality_gate_report_handles_missing_fields() -> None:
    agg_result = AggregateResult(language_style={}, traditional_culture={})
    chunk_repo = _StubChunkRepo([])

    report = _build_quality_gate_report("run-y", agg_result, chunk_repo)

    assert report["tone_distribution_non_empty_rate"] == 0.0
    assert report["imagery_density_non_null_rate"] == 0.0
    # 2026-08-13 P2-3 无 imagery 数据按"不通过"处理（保守）：0/0 不等于达标
    assert report["imagery_lexicon_null_chunk_ratio"] == 1.0
    assert report["imagery_lexicon_null_chunk_ids"] == []


def test_build_lexical_curve_quality_report_tracks_late_zero_chunks() -> None:
    report = _build_lexical_curve_quality_report(
        [
            (0, 0.1, 0.0, 0.1, 0.1, 0.2, 0.3),
            (1, 0.0, 0.0, 0.0, 0.0, 0.2, 0.3),
            (2, 0.0, 0.0, 0.0, 0.0, 0.2, 0.3),
            (3, 0.0, 0.0, 0.0, 0.0, 0.2, 0.3),
        ]
    )

    assert report["lexical_curve_zero_chunk_ratio"] == 0.75
    assert report["lexical_curve_zero_chunk_ids"] == [1, 2, 3]
    assert report["lexical_curve_late_start_index"] == 2
    assert report["lexical_curve_late_zero_chunk_ratio"] == 1.0
    assert report["lexical_curve_late_zero_chunk_ids"] == [2, 3]
