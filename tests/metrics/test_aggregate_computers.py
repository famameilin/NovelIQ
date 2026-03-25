from src.metrics.aggregate.computers import compute_language_style_metrics
from src.metrics.aggregate.types import TextData


def test_compute_language_style_metrics_tone_distribution_sums_to_one() -> None:
    text_data = TextData(texts=["测试文本"], all_tokens=["测试", "文本"])
    emotional_valences = ["strong_positive", "mild_positive", "neutral", "negative"]

    result = compute_language_style_metrics(text_data, emotional_valences)
    tone_distribution = result.get("tone_distribution", {})

    assert isinstance(tone_distribution, dict)
    assert tone_distribution
    assert abs(sum(tone_distribution.values()) - 1.0) < 1e-9
    assert tone_distribution.get("mild_negative") == 0.25


def test_compute_language_style_metrics_tone_distribution_empty_when_no_data() -> None:
    text_data = TextData(texts=["测试文本"], all_tokens=["测试", "文本"])

    result = compute_language_style_metrics(text_data, None)

    assert result.get("tone_distribution") == {}
