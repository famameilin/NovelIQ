"""
叙事时间轴核心算法单元测试。

测试范围:
- compute_importance_score: 重要性分数计算
- compute_four_phases: 四阶段划分算法
- calculate_tension_percentile: 张力百分位
- compose_composite_timeline_nodes: 第二轮复合节点分组
- serialize_timeline_node / serialize_timeline_composite_node: 双层节点合同序列化
"""

from __future__ import annotations

import pytest

from src.metrics.timeline_metrics import (
    GraphChangeDTO,
    LifecycleEventDTO,
    NarrativePhase,
    PlotFlagsDTO,
    TimelineNodeDTO,
    calculate_tension_percentile,
    compose_composite_timeline_nodes,
    compute_four_phases,
    compute_importance_score,
    convert_to_timeline_phases,
    serialize_timeline_composite_node,
    serialize_timeline_node,
)


# 2026-08-07 用于构造时间轴关系章节图变化
def create_relation_graph_change(
    *,
    relation_version_id: int,
    relation_change_kind: str,
) -> GraphChangeDTO:
    """2026-08-07 用于构造关系原子节点所需的章节图变化"""
    return GraphChangeDTO(
        change_id=f"relation:{relation_version_id}",
        change_kind="relation",
        graph_version_id=f"graph-version-{relation_version_id}",
        chapter_id=3,
        fact_id=f"fact-{relation_version_id}",
        fact_revision=1,
        effective_chunk_id=relation_version_id,
        changes=[{"change_kind": relation_change_kind, "fact_id": f"fact-{relation_version_id}"}],
        relation_id=f"relation-id-{relation_version_id}",
        relation_version_id=relation_version_id,
        relation_revision=1,
        from_char="顾承渊",
        to_char="苏映雪",
        relation_type="盟友",
        relation_change_kind=relation_change_kind,
        directionality="directed",
    )


# 2026-08-07 用于构造时间轴原子节点
def create_node(
    *,
    node_id: str,
    anchor_chunk_id: int,
    progress: float,
    importance_score: float,
    level: int = 2,
    node_type: str = "plot",
    node_subtype: str = "plot",
    phase_name: str = "发展期",
    plot_flags: PlotFlagsDTO | None = None,
    graph_changes: list[GraphChangeDTO] | None = None,
    lifecycle_events: list[LifecycleEventDTO] | None = None,
    characters: list[str] | None = None,
    composite_group_hint: tuple[str, ...] | None = None,
) -> TimelineNodeDTO:
    return TimelineNodeDTO(
        node_id=node_id,
        anchor_chunk_id=anchor_chunk_id,
        progress=progress,
        importance_score=importance_score,
        level=level,
        summary=node_id,
        characters=characters or (["角色A", "角色B"] if node_type == "relation" else ["角色A"]),
        phase_name=phase_name,  # type: ignore[arg-type]
        node_type=node_type,  # type: ignore[arg-type]
        node_subtype=node_subtype,  # type: ignore[arg-type]
        score_breakdown={"score": importance_score},
        plot_flags=plot_flags,
        graph_changes=graph_changes,
        lifecycle_events=lifecycle_events,
        composite_group_hint=composite_group_hint,
    )


class TestComputeImportanceScore:
    def test_high_score_returns_level_one(self):
        score, level = compute_importance_score(
            {
                "pivot": 3.0,
                "cliffhanger": 2.0,
                "tension": 2.0,
                "event_type": 1.2,
            }
        )
        assert score == pytest.approx(8.2)
        assert level == 1

    def test_medium_score_returns_level_two(self):
        score, level = compute_importance_score(
            {
                "change_type_weight": 2.4,
                "pair_importance": 1.2,
                "phase_rarity": 0.8,
            }
        )
        assert score == pytest.approx(4.4)
        assert level == 2

    def test_low_score_returns_level_three(self):
        score, level = compute_importance_score(
            {
                "tension": 0.4,
                "event_type": 0.4,
            }
        )
        assert score == pytest.approx(0.8)
        assert level == 3


class TestComputeFourPhases:
    def test_short_novel_uses_fixed_ratio(self):
        tension_scores = [0.1] * 10
        chunk_ids = list(range(1, 11))

        phases = compute_four_phases(tension_scores, chunk_ids)

        assert len(phases) == 4
        assert [phase.name for phase in phases] == ["引入期", "发展期", "高潮期", "收束期"]

    def test_ultra_short_novel_single_phase_fallback(self):
        """2026-08-13 用于验证 1~4 个 chunk 时不会越界（此前收束期取 chunk_ids[boundary_3+1] 直接 IndexError）"""
        for total in range(1, 5):
            chunk_ids = list(range(1, total + 1))
            phases = compute_four_phases([0.1] * total, chunk_ids)
            assert len(phases) == 1
            assert phases[0].name == "引入期"
            assert phases[0].start == chunk_ids[0]
            assert phases[0].end == chunk_ids[-1]
            assert phases[0].ratio == pytest.approx(1.0)

    def test_short_novel_boundaries_stay_in_range(self):
        """2026-08-13 用于验证 5~19 个 chunk 时四阶段边界均不越界"""
        for total in range(5, 20):
            chunk_ids = list(range(1, total + 1))
            phases = compute_four_phases([0.1] * total, chunk_ids)
            assert len(phases) == 4
            for phase in phases:
                assert 1 <= phase.start <= total
                assert 1 <= phase.end <= total
                assert phase.start <= phase.end

    def test_long_novel_uses_peak_based_split(self):
        tension_scores = [0.1] * 40 + [0.9] + [0.1] * 59
        chunk_ids = list(range(1, 101))

        phases = compute_four_phases(tension_scores, chunk_ids)

        climax_phase = next(phase for phase in phases if phase.name == "高潮期")
        assert 30 <= chunk_ids.index(climax_phase.start) <= 50

    def test_monotonic_decreasing_peak_at_start_no_inverted_climax(self):
        """2026-08-13 修复 P1：张力单调递减（global peak 落在首 chunk）时，
        此前高潮期 climax_start > climax_end 倒置、ratio 为负；修复后区间合法不重叠。"""
        tension_scores = [0.9] + [0.8 - i * 0.01 for i in range(99)]
        chunk_ids = list(range(1, 101))

        phases = compute_four_phases(tension_scores, chunk_ids)

        assert [phase.name for phase in phases] == ["引入期", "发展期", "高潮期", "收束期"]
        for phase in phases:
            assert phase.start <= phase.end
            assert phase.ratio >= 0.0
        # 四阶段覆盖全书且不重叠：ratio 总和为 1
        assert sum(phase.ratio for phase in phases) == pytest.approx(1.0)

    def test_peak_at_last_chunk_still_covered_by_final_phase(self):
        """2026-08-13 修复 P1：峰值落在末 chunk 时，收束期此前退化为 0.0 空区间、
        末章不入任何阶段；修复后收束期覆盖剩余区间。"""
        tension_scores = [0.1] * 99 + [0.9]
        chunk_ids = list(range(1, 101))

        phases = compute_four_phases(tension_scores, chunk_ids)

        assert [phase.name for phase in phases] == ["引入期", "发展期", "高潮期", "收束期"]
        for phase in phases:
            assert phase.start <= phase.end
            assert phase.ratio >= 0.0
        assert sum(phase.ratio for phase in phases) == pytest.approx(1.0)
        # 末 chunk（峰值）必须落在某个阶段区间内
        assert any(phase.start <= chunk_ids[-1] <= phase.end for phase in phases)


class TestCalculateTensionPercentile:
    def test_normal_calculation(self):
        all_tensions = [0.0, 0.25, 0.5, 0.75, 1.0]

        assert calculate_tension_percentile(0.0, all_tensions) == 20
        assert calculate_tension_percentile(0.25, all_tensions) == 40
        assert calculate_tension_percentile(0.5, all_tensions) == 60
        assert calculate_tension_percentile(1.0, all_tensions) == 100

    def test_empty_list_returns_default(self):
        assert calculate_tension_percentile(0.5, []) == 50


class TestComposeCompositeTimelineNodes:
    def test_relation_composite_keeps_progressive_changes_but_splits_opposite_change(self):
        phases = convert_to_timeline_phases(
            [
                NarrativePhase("引入期", 1, 2, 0.2),
                NarrativePhase("发展期", 3, 6, 0.4),
                NarrativePhase("高潮期", 7, 8, 0.2),
                NarrativePhase("收束期", 9, 10, 0.2),
            ]
        )
        nodes = [
            create_node(
                node_id="relation:101",
                anchor_chunk_id=5,
                progress=0.5,
                importance_score=6.9,
                level=1,
                node_type="relation",
                node_subtype="assert",
                graph_changes=[create_relation_graph_change(relation_version_id=101, relation_change_kind="assert")],
            ),
            create_node(
                node_id="relation:102",
                anchor_chunk_id=6,
                progress=0.6,
                importance_score=6.3,
                level=1,
                node_type="relation",
                node_subtype="reinforce",
                graph_changes=[
                    create_relation_graph_change(relation_version_id=102, relation_change_kind="reinforce")
                ],
            ),
            create_node(
                node_id="relation:103",
                anchor_chunk_id=7,
                progress=0.7,
                importance_score=6.0,
                level=1,
                node_type="relation",
                node_subtype="break",
                phase_name="高潮期",
                graph_changes=[create_relation_graph_change(relation_version_id=103, relation_change_kind="break")],
            ),
        ]

        composite_nodes = compose_composite_timeline_nodes(nodes, phases)
        relation_composites = [node for node in composite_nodes if node.node_type == "relation"]

        assert len(relation_composites) == 2
        assert relation_composites[0].child_node_ids == ["relation:101", "relation:102"]
        assert relation_composites[0].node_subtypes == ["assert", "reinforce"]
        assert relation_composites[1].child_node_ids == ["relation:103"]
        assert relation_composites[1].node_subtypes == ["break"]

    def test_plot_composite_groups_adjacent_nodes_with_same_hint(self):
        phases = convert_to_timeline_phases(
            [
                NarrativePhase("引入期", 1, 3, 0.25),
                NarrativePhase("发展期", 4, 6, 0.25),
                NarrativePhase("高潮期", 7, 9, 0.25),
                NarrativePhase("收束期", 10, 12, 0.25),
            ]
        )
        shared_flags = PlotFlagsDTO(is_pivot=False, is_cliffhanger=True, tension_percentile=80)
        nodes = [
            create_node(
                node_id="plot:7",
                anchor_chunk_id=7,
                progress=0.58,
                importance_score=5.8,
                level=2,
                phase_name="高潮期",
                plot_flags=shared_flags,
                characters=["顾承渊", "苏映雪"],
                composite_group_hint=("冲突", "strong_negative", "no-pivot", "cliffhanger"),
            ),
            create_node(
                node_id="plot:8",
                anchor_chunk_id=8,
                progress=0.66,
                importance_score=5.4,
                level=2,
                phase_name="高潮期",
                plot_flags=shared_flags,
                characters=["顾承渊", "苏映雪"],
                composite_group_hint=("冲突", "strong_negative", "no-pivot", "cliffhanger"),
            ),
            create_node(
                node_id="plot:10",
                anchor_chunk_id=10,
                progress=0.83,
                importance_score=4.9,
                level=2,
                phase_name="收束期",
                plot_flags=shared_flags,
                characters=["顾承渊"],
                composite_group_hint=("冲突", "strong_negative", "no-pivot", "cliffhanger"),
            ),
        ]

        composite_nodes = compose_composite_timeline_nodes(nodes, phases)
        plot_composites = [node for node in composite_nodes if node.node_type == "plot"]

        assert len(plot_composites) == 2
        assert plot_composites[0].child_node_ids == ["plot:7", "plot:8"]
        assert plot_composites[0].start_chunk_id == 7
        assert plot_composites[0].end_chunk_id == 8
        assert plot_composites[1].child_node_ids == ["plot:10"]

    def test_lifecycle_composite_keeps_one_event_per_node(self):
        phases = convert_to_timeline_phases(
            [
                NarrativePhase("引入期", 1, 3, 0.25),
                NarrativePhase("发展期", 4, 6, 0.25),
                NarrativePhase("高潮期", 7, 9, 0.25),
                NarrativePhase("收束期", 10, 12, 0.25),
            ]
        )
        nodes = [
            create_node(
                node_id="lifecycle:entry:1:1",
                anchor_chunk_id=1,
                progress=0.0,
                importance_score=4.4,
                node_type="lifecycle",
                node_subtype="entry",
                phase_name="引入期",
                lifecycle_events=[LifecycleEventDTO(entity_id=1, character_name="顾承渊", lifecycle_type="entry")],
            ),
            create_node(
                node_id="lifecycle:exit:1:12",
                anchor_chunk_id=12,
                progress=1.0,
                importance_score=4.2,
                node_type="lifecycle",
                node_subtype="exit",
                phase_name="收束期",
                lifecycle_events=[LifecycleEventDTO(entity_id=1, character_name="顾承渊", lifecycle_type="exit")],
            ),
        ]

        composite_nodes = compose_composite_timeline_nodes(nodes, phases)
        lifecycle_composites = [node for node in composite_nodes if node.node_type == "lifecycle"]

        assert len(lifecycle_composites) == 2
        assert lifecycle_composites[0].child_node_ids == ["lifecycle:entry:1:1"]
        assert lifecycle_composites[1].child_node_ids == ["lifecycle:exit:1:12"]


class TestSerializeTimelineNode:
    def test_serialize_timeline_node_uses_new_atomic_contract(self):
        node = TimelineNodeDTO(
            node_id="relation:101",
            anchor_chunk_id=8,
            progress=0.4,
            importance_score=6.7,
            level=1,
            summary="顾承渊与苏映雪结盟",
            characters=["顾承渊", "苏映雪"],
            phase_name="发展期",
            node_type="relation",
            node_subtype="assert",
            score_breakdown={"change_type_weight": 2.4, "pair_importance": 1.1},
            graph_changes=[create_relation_graph_change(relation_version_id=101, relation_change_kind="assert")],
        )

        payload = serialize_timeline_node(node)

        assert set(payload) == {
            "node_id",
            "anchor_chunk_id",
            "progress",
            "importance_score",
            "level",
            "summary",
            "characters",
            "phase_name",
            "node_type",
            "node_subtype",
            "score_breakdown",
            "plot_flags",
            "graph_changes",
            "lifecycle_events",
        }
        assert payload["graph_changes"][0]["relation_id"] == "relation-id-101"
        assert payload["graph_changes"][0]["relation_change_kind"] == "assert"

    def test_serialize_timeline_composite_node_uses_dual_layer_contract(self):
        phases = convert_to_timeline_phases(
            [
                NarrativePhase("引入期", 1, 3, 0.25),
                NarrativePhase("发展期", 4, 6, 0.25),
                NarrativePhase("高潮期", 7, 9, 0.25),
                NarrativePhase("收束期", 10, 12, 0.25),
            ]
        )
        composite_node = compose_composite_timeline_nodes(
            [
                create_node(
                    node_id="relation:101",
                    anchor_chunk_id=8,
                    progress=0.66,
                    importance_score=6.7,
                    level=1,
                    node_type="relation",
                    node_subtype="assert",
                    phase_name="高潮期",
                    graph_changes=[
                        create_relation_graph_change(relation_version_id=101, relation_change_kind="assert")
                    ],
                )
            ],
            phases,
        )[0]

        payload = serialize_timeline_composite_node(composite_node)

        assert set(payload) == {
            "node_id",
            "anchor_chunk_id",
            "start_chunk_id",
            "end_chunk_id",
            "progress",
            "start_progress",
            "end_progress",
            "importance_score",
            "level",
            "summary",
            "characters",
            "phase_name",
            "node_type",
            "node_subtypes",
            "representative_node_id",
            "child_node_ids",
        }
        assert payload["representative_node_id"] == "relation:101"
        assert payload["child_node_ids"] == ["relation:101"]
