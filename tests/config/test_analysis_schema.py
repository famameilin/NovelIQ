import pytest

from src.config.constants import STAGE_PROGRESS_MILESTONES
from src.config.schemas import (
    _parse_metrics_settings,
    _parse_topic_model_settings,
)
from src.config.schemas.analysis import ProgressSettings


def test_progress_settings_defaults_from_constants() -> None:
    settings = ProgressSettings()

    expected_start = 0.0
    for stage, expected_end in STAGE_PROGRESS_MILESTONES.items():
        stage_range = getattr(settings, stage)
        assert stage_range.start == expected_start
        assert stage_range.end == expected_end
        expected_start = expected_end


def test_parse_topic_model_settings_reads_flat_and_lda_fields() -> None:
    settings = _parse_topic_model_settings(
        {
            "num_topics": 30,
            "passes": 12,
            "iterations": 600,
            "lda": {
                "alpha": "auto",
                "eta": "auto",
                "random_state": 42,
                "lda_batch_size": 2000,
                "minimum_probability": 0.01,
                "no_below": 5,
                "no_above": 0.5,
            },
        }
    )

    assert settings.num_topics == 30
    assert settings.passes == 12
    assert settings.iterations == 600
    assert settings.lda.random_state == 42
    assert settings.lda.no_below == 5


def test_parse_topic_model_settings_rejects_removed_chunksize() -> None:
    with pytest.raises(ValueError, match="chunksize.*lda_batch_size"):
        _parse_topic_model_settings({"lda": {"chunksize": 2000}})


def test_parse_topic_model_settings_defaults() -> None:
    settings = _parse_topic_model_settings(None)

    assert settings.num_topics == 25
    assert settings.passes == 10
    assert settings.iterations == 500
    assert settings.lda.alpha == "auto"
    assert settings.lda.no_above == 0.5


def test_parse_metrics_settings_reads_thresholds() -> None:
    settings = _parse_metrics_settings(
        {
            "mtld_threshold": 0.7,
            "middle_collapse_min_chunks": 8,
            "character_max_iter": 50,
        }
    )

    assert settings.mtld_threshold == 0.7
    assert settings.middle_collapse_min_chunks == 8
    assert settings.character_max_iter == 50


def test_parse_metrics_settings_defaults() -> None:
    settings = _parse_metrics_settings(None)

    assert settings.mtld_threshold == 0.72
    assert settings.middle_collapse_min_chunks == 10
    assert settings.character_max_iter == 100


def test_parse_metrics_settings_reads_lowess_fields() -> None:
    settings = _parse_metrics_settings({"lowess_bandwidth": 0.05, "lowess_min_points": 10})

    assert settings.lowess_bandwidth == 0.05
    assert settings.lowess_min_points == 10


def test_parse_metrics_settings_rejects_invalid_lowess_bandwidth() -> None:
    for bad in (0, -0.5, 1.5, "0.02"):
        with pytest.raises(ValueError, match="lowess_bandwidth"):
            _parse_metrics_settings({"lowess_bandwidth": bad})


def test_parse_metrics_settings_rejects_invalid_lowess_min_points() -> None:
    for bad in (0, -1, 2.5):
        with pytest.raises(ValueError, match="lowess_min_points"):
            _parse_metrics_settings({"lowess_min_points": bad})
