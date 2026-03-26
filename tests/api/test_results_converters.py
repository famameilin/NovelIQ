from src.api.routes.results_converters import _convert_culture_stats, _convert_style_stats
from src.metrics.aggregate import AggregateResult


def test_convert_style_stats_tone_distribution_default_empty_dict() -> None:
    result = AggregateResult(language_style={"vocab_breadth": 0.42})

    style_stats = _convert_style_stats(result)

    assert style_stats is not None
    assert style_stats.tone_distribution == {}


def test_convert_culture_stats_maps_imagery_density() -> None:
    result = AggregateResult(traditional_culture={"imagery_density": 0.1234})

    culture_stats = _convert_culture_stats(result)

    assert culture_stats is not None
    assert culture_stats.imagery_density == 0.1234


def test_convert_culture_stats_imagery_density_default_zero() -> None:
    result = AggregateResult(traditional_culture={"idiom_density": 0.0})

    culture_stats = _convert_culture_stats(result)

    assert culture_stats is not None
    assert culture_stats.imagery_density == 0.0
