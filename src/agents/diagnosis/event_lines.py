"""按事件集合选事件线：有章跨度时保留一条全书主线并补足独立弧线"""

from __future__ import annotations

from collections.abc import Mapping

SEARCH_NODE_LIMIT = 200_000


def _maximal_sets(tree_sets: Mapping[str, frozenset[str]]) -> list[tuple[str, frozenset[str]]]:
    """去掉被其他候选事件集包含的树，重复事件集只留第一棵"""
    ordered = sorted(tree_sets.items(), key=lambda item: (-len(item[1]), item[0]))
    kept: list[tuple[str, frozenset[str]]] = []
    for tree_id, events in ordered:
        if any(events <= other for _, other in kept):
            continue
        kept.append((tree_id, events))
    return kept


def _select_bounded(
    tree_sets: Mapping[str, frozenset[str]],
    spans: Mapping[str, int],
    *,
    minimum: int,
    maximum: int,
    broad_span: int,
    max_broad: int,
) -> list[str]:
    """贪心覆盖：全书主线最多 max_broad 条，其余名额按增量覆盖补独立弧线"""
    events_order = sorted({event for events in tree_sets.values() for event in events})
    bit = {event: index for index, event in enumerate(events_order)}
    masks = {tree_id: sum(1 << bit[event] for event in events) for tree_id, events in tree_sets.items()}
    broad = {tree_id for tree_id in tree_sets if spans.get(tree_id, 0) > broad_span}
    chosen: list[str] = []
    covered = 0
    broad_used = 0
    while len(chosen) < maximum:
        best: str | None = None
        best_gain = 0
        best_size = 0
        for tree_id, mask in masks.items():
            if tree_id in chosen:
                continue
            if tree_id in broad and broad_used >= max_broad:
                continue
            gain = (mask & ~covered).bit_count()
            size = len(tree_sets[tree_id])
            if gain > best_gain or (gain == best_gain and gain and size < best_size):
                best, best_gain, best_size = tree_id, gain, size
        if best is None or best_gain == 0:
            break
        chosen.append(best)
        covered |= masks[best]
        if best in broad:
            broad_used += 1
    if len(chosen) < minimum:
        padding = sorted(
            (tree_id for tree_id in tree_sets if tree_id not in chosen),
            key=lambda tree_id: (tree_id in broad, len(tree_sets[tree_id]), tree_id),
        )
        chosen.extend(padding[: minimum - len(chosen)])
    return chosen if len(chosen) >= minimum else []


def select_event_lines(
    tree_sets: Mapping[str, frozenset[str]],
    minimum: int,
    maximum: int,
    *,
    spans: Mapping[str, int] | None = None,
    broad_span: int = 0,
    max_broad: int = 1,
) -> list[str]:
    """返回覆盖事件最多的事件树；有章跨度时全书主线不超过 max_broad 条

    spans 给出每棵树的章节跨度；不传时按精确最大覆盖选，覆盖相同时取事件总数最少。
    """
    usable = {tree_id: events for tree_id, events in tree_sets.items() if events}
    if len(usable) < minimum:
        return []
    if spans is not None:
        return _select_bounded(
            usable,
            spans,
            minimum=minimum,
            maximum=maximum,
            broad_span=broad_span,
            max_broad=max_broad,
        )
    maximal = _maximal_sets(usable)
    events_order = sorted({event for events in usable.values() for event in events})
    bit = {event: index for index, event in enumerate(events_order)}
    masks = [sum(1 << bit[event] for event in events) for _, events in maximal]
    weights = [len(events) for _, events in maximal]
    keys = [tree_id for tree_id, _ in maximal]
    count = len(maximal)

    best_cover = -1
    best_cost = 0
    best_choice: list[int] = []
    nodes = 0
    exhausted = False

    def search(index: int, slots: int, covered: int, cost: int, chosen: list[int]) -> None:
        nonlocal best_cover, best_cost, best_choice, nodes, exhausted
        nodes += 1
        if nodes > SEARCH_NODE_LIMIT:
            exhausted = True
            return
        covered_count = covered.bit_count()
        if covered_count > best_cover or (covered_count == best_cover and cost < best_cost):
            best_cover = covered_count
            best_cost = cost
            best_choice = list(chosen)
        if slots == 0 or index == count:
            return
        gains = sorted(
            ((masks[position] & ~covered).bit_count() for position in range(index, count)),
            reverse=True,
        )
        if covered_count + sum(gains[:slots]) < best_cover:
            return
        gain = (masks[index] & ~covered).bit_count()
        if gain:
            chosen.append(index)
            search(index + 1, slots - 1, covered | masks[index], cost + weights[index], chosen)
            chosen.pop()
        if not exhausted:
            search(index + 1, slots, covered, cost, chosen)

    search(0, min(maximum, len(maximal)), 0, 0, [])
    chosen = [keys[index] for index in sorted(best_choice)]
    if len(chosen) < minimum:
        chosen_set = set(chosen)
        padding = sorted(
            (tree_id for tree_id in usable if tree_id not in chosen_set),
            key=lambda tree_id: (len(usable[tree_id]), tree_id),
        )
        chosen.extend(padding[: minimum - len(chosen)])
    return chosen
