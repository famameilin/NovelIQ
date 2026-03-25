from src.metrics.aggregate.computers import compute_language_style_metrics
from src.metrics.aggregate.types import TextData


def test_compute_language_style_metrics_tone_distribution_sums_to_one() -> None:
    text_data = TextData(
        texts=["\u7b80\u5355\u6587\u672c"],
        all_tokens=["\u7b80\u5355", "\u6587\u672c"],
    )
    dialogue_tones = [
        "\u5f3a\u786c",
        "\u6e29\u548c",
        "\u5f3a\u786c",
        "\u8bbd\u523a",
    ]

    result = compute_language_style_metrics(text_data, dialogue_tones)
    tone_distribution = result.get("tone_distribution", {})

    assert isinstance(tone_distribution, dict)
    assert tone_distribution
    assert abs(sum(tone_distribution.values()) - 1.0) < 1e-9
    assert tone_distribution == {
        "\u5f3a\u786c": 0.5,
        "\u6e29\u548c": 0.25,
        "\u8bbd\u523a": 0.25,
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
