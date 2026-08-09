from src.config.schemas import (
    _parse_metrics_settings,
    _parse_progress_settings,
    _parse_topic_model_settings,
)


def test_parse_progress_settings_reads_stage_ranges() -> None:
    settings = _parse_progress_settings(
        {
            "preprocess": {"start": 0, "end": 10},
            "annotate": {"start": 10, "end": 80},
            "diagnose": {"start": 95, "end": 100},
        }
    )

    assert settings.annotate.start == 10
    assert settings.annotate.end == 80
    assert settings.diagnose.start == 95


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
                "chunksize": 2000,
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
            "fourier_smooth_keep_ratio": 0.2,
        }
    )

    assert settings.mtld_threshold == 0.7
    assert settings.middle_collapse_min_chunks == 8
    assert settings.character_max_iter == 50
    assert settings.fourier_smooth_keep_ratio == 0.2


def test_parse_metrics_settings_defaults() -> None:
    settings = _parse_metrics_settings(None)

    assert settings.mtld_threshold == 0.72
    assert settings.middle_collapse_min_chunks == 10
    assert settings.character_max_iter == 100
    assert settings.fourier_smooth_keep_ratio == 0.1
