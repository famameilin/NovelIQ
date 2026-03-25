from src.metrics.lexicon_metrics import count_mixed_hits, count_token_hits


def test_mixed_hits_detects_phrase_substring_when_token_miss() -> None:
    text = "青衫剑客踏月而来"
    tokens = ["青衫", "剑客", "踏月", "而来"]

    assert count_token_hits(tokens, ["青衫剑客"]) == 0
    assert count_mixed_hits(text, tokens, ["青衫剑客"]) == 1


def test_mixed_hits_detects_multi_word_phrase() -> None:
    text = "the golden core remains stable"
    tokens = ["the", "golden", "core", "remains", "stable"]

    assert count_token_hits(tokens, ["golden core"]) == 0
    assert count_mixed_hits(text, tokens, ["golden core"]) == 1
