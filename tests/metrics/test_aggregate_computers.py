from src.metrics.aggregate.computers import compute_language_style_metrics
from src.metrics.aggregate.types import TextData


def test_compute_language_style_metrics_tone_distribution_sums_to_one() -> None:
    text_data = TextData(texts=["娴嬭瘯鏂囨湰"], all_tokens=["娴嬭瘯", "鏂囨湰"])
    dialogue_tones = ["强硬", "温和", "强硬", "讽刺"]

    result = compute_language_style_metrics(text_data, dialogue_tones)
    tone_distribution = result.get("tone_distribution", {})

    assert isinstance(tone_distribution, dict)
    assert tone_distribution
    assert abs(sum(tone_distribution.values()) - 1.0) < 1e-9
    assert tone_distribution == {"强硬": 0.5, "温和": 0.25, "讽刺": 0.25}


def test_compute_language_style_metrics_tone_distribution_empty_when_no_data() -> None:
    text_data = TextData(texts=["娴嬭瘯鏂囨湰"], all_tokens=["娴嬭瘯", "鏂囨湰"])

    result = compute_language_style_metrics(text_data, None)

    assert result.get("tone_distribution") == {}
