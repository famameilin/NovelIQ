from src.metrics.style_metrics import lexicon_density


def test_mixed_lexicon_density_is_capped_at_one() -> None:
    text = "天地玄黄"
    tokens = ["天地玄黄"]
    terms = ["天地", "玄黄"]

    density = lexicon_density(tokens, terms, text=text)

    assert density == 1.0


def test_token_lexicon_density_is_capped_at_one() -> None:
    tokens = ["甲"]
    terms = ["甲", "乙"]

    density = lexicon_density(tokens, terms)

    assert density == 1.0
