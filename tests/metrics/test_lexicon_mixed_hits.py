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


def test_mixed_hits_prefers_longest_non_overlapping_phrase_matches() -> None:
    text = "渡劫飞升"
    tokens = ["渡劫飞升"]

    hits = count_mixed_hits(text, tokens, ["渡劫", "渡劫飞升"])

    assert hits == 1


def test_mixed_hits_counts_each_non_overlapping_span_once() -> None:
    text = "渡劫飞升渡劫"
    tokens = ["渡劫飞升", "渡劫"]

    hits = count_mixed_hits(text, tokens, ["渡劫", "渡劫飞升"])

    assert hits == 2
