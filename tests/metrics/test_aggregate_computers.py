from src.metrics.aggregate.computers import (
    compute_language_style_metrics,
    compute_traditional_culture_metrics,
)
from src.metrics.aggregate.types import CultureData, TextData
from src.metrics.style_metrics_extra import compute_imagery_density


def test_compute_language_style_metrics_tone_distribution_sums_to_one() -> None:
    text_data = TextData(
        texts=["\u7b80\u5355\u6587\u672c"],
        all_tokens=["\u7b80\u5355", "\u6587\u672c"],
    )
    dialogue_tones = [
        "愤怒",
        "平静",
        "愤怒",
        "嘲讽",
    ]

    result = compute_language_style_metrics(text_data, dialogue_tones)
    tone_distribution = result.get("tone_distribution", {})

    assert isinstance(tone_distribution, dict)
    assert tone_distribution
    assert abs(sum(tone_distribution.values()) - 1.0) < 1e-9
    assert tone_distribution == {
        "愤怒": 0.5,
        "平静": 0.25,
        "嘲讽": 0.25,
    }


def test_compute_language_style_metrics_tone_distribution_empty_when_no_data() -> None:
    text_data = TextData(
        texts=["\u7b80\u5355\u6587\u672c"],
        all_tokens=["\u7b80\u5355", "\u6587\u672c"],
    )

    result = compute_language_style_metrics(text_data, None)

    assert result.get("tone_distribution") == {}


def test_compute_language_style_metrics_category_density_hits_multi_char_terms() -> None:
    text = (
        "\u957f\u5251 "
        "\u5934\u9885 "
        "\u7236\u4eb2 "
        "\u5b97\u95e8 "
        "\u547d\u4ee4 "
        "\u884c\u8d70 "
        "\u601d\u8003 "
        "\u5de8\u5927 "
        "\u6b22\u559c "
        "\u7ea2\u8272"
    )
    text_data = TextData(
        texts=[text],
        all_tokens=[
            "\u957f\u5251",
            "\u5934\u9885",
            "\u7236\u4eb2",
            "\u5b97\u95e8",
            "\u547d\u4ee4",
            "\u884c\u8d70",
            "\u601d\u8003",
            "\u5de8\u5927",
            "\u6b22\u559c",
            "\u7ea2\u8272",
        ],
    )

    result = compute_language_style_metrics(text_data, None)

    assert result["category_density_combat"] > 0.0
    assert result["category_density_body"] > 0.0
    assert result["category_density_relation"] > 0.0
    assert result["category_density_faction"] > 0.0
    assert result["category_density_command"] > 0.0
    assert result["category_density_action"] > 0.0
    assert result["category_density_psychology"] > 0.0
    assert result["category_density_measure"] > 0.0
    assert result["category_density_emotion"] > 0.0
    assert result["category_density_color"] > 0.0


def test_compute_traditional_culture_metrics_keeps_whole_text_imagery_density() -> None:
    texts = ["风风风风", "风"]
    culture_data = CultureData(imagery_densities=[0.0, 1.0])
    expected = compute_imagery_density(texts)

    result = compute_traditional_culture_metrics(culture_data, texts)

    assert expected != 0.5
    assert result["imagery_density"] == expected


def test_compute_traditional_culture_metrics_is_invariant_to_chunk_splitting() -> None:
    full_text = ["风月山水梅兰竹菊"]
    split_text = ["风月", "山水", "梅兰", "竹菊"]

    full_result = compute_traditional_culture_metrics(
        CultureData(imagery_densities=[0.25]),
        full_text,
    )
    split_result = compute_traditional_culture_metrics(
        CultureData(imagery_densities=[1.0, 1.0, 1.0, 1.0]),
        split_text,
    )

    assert full_result["imagery_density"] == split_result["imagery_density"]
