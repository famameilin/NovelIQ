from src.metrics.aggregate_metrics import AggregateResult
from src.workflows.aggregate import _build_quality_gate_report


class _StubChunkRepo:
    def __init__(self, rows):
        self._rows = rows

    def fetch_chunk_cultures_full(self, run_id: str):
        return self._rows


def test_build_quality_gate_report_flags_all_zero_chunks() -> None:
    agg_result = AggregateResult(
        language_style={"tone_distribution": {"neutral": 1.0}},
        traditional_culture={"imagery_density": 0.2},
    )
    chunk_repo = _StubChunkRepo(
        [
            (0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            (1, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0),
        ]
    )

    report = _build_quality_gate_report("run-x", agg_result, chunk_repo)

    assert report["tone_distribution_non_empty_rate"] == 1.0
    assert report["imagery_density_non_null_rate"] == 1.0
    assert report["culture_all_zero_chunk_ratio"] == 0.5
    assert report["culture_all_zero_chunk_ids"] == [0]


def test_build_quality_gate_report_handles_missing_fields() -> None:
    agg_result = AggregateResult(language_style={}, traditional_culture={})
    chunk_repo = _StubChunkRepo([])

    report = _build_quality_gate_report("run-y", agg_result, chunk_repo)

    assert report["tone_distribution_non_empty_rate"] == 0.0
    assert report["imagery_density_non_null_rate"] == 0.0
    assert report["culture_all_zero_chunk_ratio"] == 0.0
    assert report["culture_all_zero_chunk_ids"] == []
