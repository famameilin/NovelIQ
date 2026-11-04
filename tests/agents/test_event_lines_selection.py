"""事件线选择的精确最大覆盖与件数补足"""

from src.agents.diagnosis.event_lines import select_event_lines


def _coverage(tree_sets, selected):
    covered = set().union(*(tree_sets[tree_id] for tree_id in selected))
    return len(covered), sum(len(tree_sets[tree_id]) for tree_id in selected)


def test_selects_maximum_coverage_instead_of_greedy_first_pick():
    tree_sets = {
        "a": frozenset({1, 2, 3, 4}),
        "b": frozenset({1, 2, 5}),
        "c": frozenset({3, 4, 6}),
        "d": frozenset({5, 6}),
    }

    selected = select_event_lines(tree_sets, 1, 2)

    assert _coverage(tree_sets, selected) == (6, 6)


def test_prefers_smaller_total_events_when_coverage_is_equal():
    tree_sets = {
        "a": frozenset({1, 2, 3, 4}),
        "b": frozenset({1, 2, 3, 5}),
        "c": frozenset({4, 5}),
    }

    selected = select_event_lines(tree_sets, 2, 2)

    assert _coverage(tree_sets, selected) == (5, 6)


def test_pads_to_minimum_when_candidates_collapse_to_one_group():
    tree_sets = {name: frozenset({1}) for name in ("a", "b", "c", "d", "e")}

    selected = select_event_lines(tree_sets, 5, 10)

    assert len(selected) == 5
    assert _coverage(tree_sets, selected) == (1, 5)


def test_returns_empty_when_usable_trees_below_minimum():
    tree_sets = {"a": frozenset({1}), "b": frozenset(), "c": frozenset()}

    assert select_event_lines(tree_sets, 5, 10) == []


def test_bounded_selection_keeps_one_broad_line_and_fills_with_arcs():
    broad = frozenset(range(1, 101))
    arcs = {
        f"arc{index}": frozenset(range(index * 10 + 1, index * 10 + 11)) | {200 + index}
        for index in range(9)
    }
    tree_sets = {"main": broad, **arcs}
    spans = {"main": 100, **dict.fromkeys(arcs, 10)}

    selected = select_event_lines(tree_sets, 5, 10, spans=spans, broad_span=40, max_broad=1)

    assert len(selected) == 10
    assert selected[0] == "main"
    assert set(selected[1:]) == set(arcs)


def test_bounded_selection_skips_second_broad_line():
    tree_sets = {
        "main": frozenset(range(1, 11)),
        "wide": frozenset(range(1, 10)),
        "arc": frozenset({11}),
    }
    spans = {"main": 100, "wide": 100, "arc": 5}

    selected = select_event_lines(tree_sets, 2, 2, spans=spans, broad_span=50, max_broad=1)

    assert selected == ["main", "arc"]


def test_bounded_padding_prefers_arc_over_second_broad_line():
    tree_sets = {
        "main": frozenset({1, 2, 3, 4}),
        "wide": frozenset({1, 2, 3, 4, 5}),
        "arc": frozenset({1, 2}),
    }
    spans = {"main": 100, "wide": 90, "arc": 10}

    selected = select_event_lines(tree_sets, 2, 2, spans=spans, broad_span=50, max_broad=1)

    assert selected == ["wide", "arc"]
