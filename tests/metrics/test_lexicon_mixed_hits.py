"""phrase 模式匹配测试"""

from src.metrics.lexicon_metrics import GroupedMixedMatcher, count_mixed_hits, get_emotion_spans, term_mixed_counts


def test_mixed_hits_detects_phrase_substring_when_token_miss() -> None:
    text = "青衫剑客踏月而来"
    tokens = ["青衫", "剑客", "踏月", "而来"]

    assert count_mixed_hits(text, tokens, ["青衫剑客"]) == 1


def test_mixed_hits_detects_multi_word_phrase() -> None:
    text = "the golden core remains stable"
    tokens = ["the", "golden", "core", "remains", "stable"]

    assert count_mixed_hits(text, tokens, ["golden core"]) == 1


def test_mixed_hits_prefers_longest_non_overlapping_phrase_matches() -> None:
    text = "渡劫飞升"
    tokens = ["渡劫飞升"]

    hits = count_mixed_hits(text, tokens, ["渡劫", "渡劫飞升"])

    assert hits == 1


def test_shorter_match_survives_when_longer_same_start_overlaps_selected_phrase() -> None:
    assert term_mixed_counts("abcdefghijk", [], ["abcde", "defghijk", "abc"]) == {"defghijk": 1, "abc": 1}


def test_suffix_phrases_and_repeated_matches_keep_longest_priority() -> None:
    assert term_mixed_counts("渡劫飞升渡劫飞升", [], ["渡劫", "飞升", "渡劫飞升"]) == {"渡劫飞升": 2}


def test_single_character_terms_require_tokens_and_emotion_spans_keep_positions() -> None:
    assert term_mixed_counts("喜悲喜", [], ["喜"]) == {}
    assert get_emotion_spans("喜悲喜", ["喜", "悲", "喜"], ["喜"]) == [(0, 1, "喜"), (2, 3, "喜")]


def test_changed_lexicon_content_is_not_hidden_by_matcher_cache() -> None:
    terms = ["渡劫"]
    assert term_mixed_counts("渡劫飞升", [], terms) == {"渡劫": 1}
    terms.append("渡劫飞升")
    assert term_mixed_counts("渡劫飞升", [], terms) == {"渡劫飞升": 1}


def test_mixed_hits_counts_each_non_overlapping_span_once() -> None:
    text = "渡劫飞升渡劫"
    tokens = ["渡劫飞升", "渡劫"]

    hits = count_mixed_hits(text, tokens, ["渡劫", "渡劫飞升"])

    assert hits == 2


def test_mixed_hits_deduplicates_phrase_and_component_token_matches() -> None:
    text = "渡劫飞升"
    tokens = ["渡劫", "飞升"]

    hits = count_mixed_hits(text, tokens, ["渡劫", "飞升", "渡劫飞升"])

    assert hits == 1


def test_grouped_hits_preserve_independent_overlap_rules() -> None:
    text = "喜渡劫飞升渡劫"
    tokens = ["喜", "渡劫", "飞升", "渡劫"]
    groups = {"event": ["渡劫飞升", "渡劫"], "emotion": ["喜", "渡劫", "飞升"], "empty": []}
    assert GroupedMixedMatcher(groups).count(text, tokens) == {
        category: count_mixed_hits(text, tokens, terms) for category, terms in groups.items() if terms
    }
