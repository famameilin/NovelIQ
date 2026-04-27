"""
叙事时间轴核心算法单元测试。

测试范围:
- compute_importance_score: 重要性分数计算
- compute_timeline_node_budget: 自适应预算
- compute_four_phases: 四阶段划分算法
- select_timeline_nodes: 节点筛选与去重逻辑
- serialize_timeline_node: 新合同序列化
"""

from __future__ import annotations

import pytest

from src.metrics.timeline_metrics import (
    LifecycleEventDTO,
    NarrativePhase,
    PlotFlagsDTO,
    RelationEventDTO,
    TimelineBudget,
    TimelineNodeDTO,
    calculate_tension_percentile,
    compute_four_phases,
    compute_importance_score,
    compute_timeline_node_budget,
    convert_to_timeline_phases,
    select_timeline_nodes,
    serialize_timeline_node,
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


class TestComputeTimelineNodeBudget:
    def test_budget_for_short_story(self):
        budget = compute_timeline_node_budget(37)
        assert budget == TimelineBudget(min_nodes=8, target_nodes=12, max_nodes=16)

    def test_budget_for_long_story(self):
        budget = compute_timeline_node_budget(255)
        assert budget == TimelineBudget(min_nodes=14, target_nodes=30, max_nodes=40)


class TestComputeFourPhases:
    def test_short_novel_uses_fixed_ratio(self):
        tension_scores = [0.1] * 10
        chunk_ids = list(range(1, 11))

        phases = compute_four_phases(tension_scores, chunk_ids)

        assert len(phases) == 4
        assert [phase.name for phase in phases] == ["引入期", "发展期", "高潮期", "收束期"]

    def test_long_novel_uses_peak_based_split(self):
        tension_scores = [0.1] * 40 + [0.9] + [0.1] * 59
        chunk_ids = list(range(1, 101))

        phases = compute_four_phases(tension_scores, chunk_ids)

        climax_phase = next(phase for phase in phases if phase.name == "高潮期")
        assert 30 <= chunk_ids.index(climax_phase.start) <= 50


class TestCalculateTensionPercentile:
    def test_normal_calculation(self):
        all_tensions = [0.0, 0.25, 0.5, 0.75, 1.0]

        assert calculate_tension_percentile(0.0, all_tensions) == 20
        assert calculate_tension_percentile(0.25, all_tensions) == 40
        assert calculate_tension_percentile(0.5, all_tensions) == 60
        assert calculate_tension_percentile(1.0, all_tensions) == 100

    def test_empty_list_returns_default(self):
        assert calculate_tension_percentile(0.5, []) == 50


class TestSelectTimelineNodes:
    def create_node(
        self,
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
        relation_events: list[RelationEventDTO] | None = None,
        lifecycle_events: list[LifecycleEventDTO] | None = None,
    ) -> TimelineNodeDTO:
        return TimelineNodeDTO(
            node_id=node_id,
            anchor_chunk_id=anchor_chunk_id,
            progress=progress,
            importance_score=importance_score,
            level=level,
            summary=node_id,
            characters=["角色A", "角色B"] if node_type == "relation" else ["角色A"],
            phase_name=phase_name,  # type: ignore[arg-type]
            node_type=node_type,  # type: ignore[arg-type]
            node_subtype=node_subtype,  # type: ignore[arg-type]
            score_breakdown={"score": importance_score},
            plot_flags=plot_flags,
            relation_events=relation_events,
            lifecycle_events=lifecycle_events,
        )

    def test_select_timeline_nodes_keeps_start_end_and_peak_plot_nodes(self):
        phases = convert_to_timeline_phases(
            [
                NarrativePhase("引入期", 1, 3, 0.3),
                NarrativePhase("发展期", 4, 6, 0.3),
                NarrativePhase("高潮期", 7, 8, 0.2),
                NarrativePhase("收束期", 9, 10, 0.2),
            ]
        )
        nodes = [
            self.create_node(
                node_id="plot:1",
                anchor_chunk_id=1,
                progress=0.0,
                importance_score=4.2,
                phase_name="引入期",
                plot_flags=PlotFlagsDTO(is_pivot=False, is_cliffhanger=False, tension_percentile=20),
            ),
            self.create_node(
                node_id="plot:7",
                anchor_chunk_id=7,
                progress=0.7,
                importance_score=7.4,
                level=1,
                phase_name="高潮期",
                plot_flags=PlotFlagsDTO(is_pivot=True, is_cliffhanger=False, tension_percentile=95),
            ),
            self.create_node(
                node_id="plot:10",
                anchor_chunk_id=10,
                progress=1.0,
                importance_score=4.1,
                phase_name="收束期",
                plot_flags=PlotFlagsDTO(is_pivot=False, is_cliffhanger=False, tension_percentile=15),
            ),
        ]

        selected = select_timeline_nodes(
            nodes=nodes,
            chunk_ids=list(range(1, 11)),
            tension_scores=[0.1, 0.2, 0.25, 0.3, 0.4, 0.6, 0.95, 0.5, 0.2, 0.1],
            phases=phases,
            budget=TimelineBudget(min_nodes=3, target_nodes=4, max_nodes=6),
        )

        selected_ids = {node.node_id for node in selected}
        assert {"plot:1", "plot:7", "plot:10"}.issubset(selected_ids)

    def test_select_timeline_nodes_allows_same_chunk_multi_type_but_dedupes_same_relation_pair(self):
        phases = convert_to_timeline_phases(
            [
                NarrativePhase("引入期", 1, 2, 0.2),
                NarrativePhase("发展期", 3, 6, 0.4),
                NarrativePhase("高潮期", 7, 8, 0.2),
                NarrativePhase("收束期", 9, 10, 0.2),
            ]
        )
        nodes = [
            self.create_node(
                node_id="plot:5",
                anchor_chunk_id=5,
                progress=0.5,
                importance_score=6.1,
                level=1,
                plot_flags=PlotFlagsDTO(is_pivot=True, is_cliffhanger=True, tension_percentile=88),
            ),
            self.create_node(
                node_id="relation:101",
                anchor_chunk_id=5,
                progress=0.5,
                importance_score=6.9,
                level=1,
                node_type="relation",
                node_subtype="新建",
                relation_events=[
                    RelationEventDTO(
                        relation_event_id=101,
                        from_char="顾承渊",
                        to_char="苏映雪",
                        relation_type="盟友",
                        change_type="新建",
                    )
                ],
            ),
            self.create_node(
                node_id="relation:102",
                anchor_chunk_id=6,
                progress=0.6,
                importance_score=6.3,
                level=1,
                node_type="relation",
                node_subtype="强化",
                relation_events=[
                    RelationEventDTO(
                        relation_event_id=102,
                        from_char="顾承渊",
                        to_char="苏映雪",
                        relation_type="盟友",
                        change_type="强化",
                    )
                ],
            ),
            self.create_node(
                node_id="lifecycle:entry:1:5",
                anchor_chunk_id=5,
                progress=0.5,
                importance_score=5.1,
                node_type="lifecycle",
                node_subtype="entry",
                lifecycle_events=[LifecycleEventDTO(entity_id=1, character_name="顾承渊", lifecycle_type="entry")],
            ),
            self.create_node(
                node_id="plot:1",
                anchor_chunk_id=1,
                progress=0.0,
                importance_score=4.2,
                phase_name="引入期",
                plot_flags=PlotFlagsDTO(is_pivot=False, is_cliffhanger=False, tension_percentile=20),
            ),
            self.create_node(
                node_id="plot:10",
                anchor_chunk_id=10,
                progress=1.0,
                importance_score=4.1,
                phase_name="收束期",
                plot_flags=PlotFlagsDTO(is_pivot=False, is_cliffhanger=False, tension_percentile=15),
            ),
        ]

        selected = select_timeline_nodes(
            nodes=nodes,
            chunk_ids=list(range(1, 11)),
            tension_scores=[0.1, 0.2, 0.25, 0.3, 0.88, 0.84, 0.4, 0.3, 0.2, 0.1],
            phases=phases,
            budget=TimelineBudget(min_nodes=5, target_nodes=6, max_nodes=8),
        )

        selected_ids = {node.node_id for node in selected}
        assert "plot:5" in selected_ids
        assert "relation:101" in selected_ids
        assert "lifecycle:entry:1:5" in selected_ids
        assert not {"relation:101", "relation:102"}.issubset(selected_ids)

    def test_select_timeline_nodes_respects_budget_ceiling(self):
        phases = convert_to_timeline_phases(
            [
                NarrativePhase("引入期", 1, 5, 0.25),
                NarrativePhase("发展期", 6, 10, 0.25),
                NarrativePhase("高潮期", 11, 15, 0.25),
                NarrativePhase("收束期", 16, 20, 0.25),
            ]
        )
        nodes = [
            self.create_node(
                node_id=f"plot:{chunk_id}",
                anchor_chunk_id=chunk_id,
                progress=(chunk_id - 1) / 19,
                importance_score=float(chunk_id) / 2,
                phase_name=phases[min((chunk_id - 1) // 5, 3)].name,
                plot_flags=PlotFlagsDTO(is_pivot=chunk_id == 12, is_cliffhanger=False, tension_percentile=50),
            )
            for chunk_id in range(1, 21)
        ]

        selected = select_timeline_nodes(
            nodes=nodes,
            chunk_ids=list(range(1, 21)),
            tension_scores=[0.1] * 11 + [0.95] + [0.1] * 8,
            phases=phases,
            budget=TimelineBudget(min_nodes=8, target_nodes=10, max_nodes=12),
        )

        assert len(selected) <= 12


class TestSerializeTimelineNode:
    def test_serialize_timeline_node_uses_new_contract(self):
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
            node_subtype="新建",
            score_breakdown={"change_type_weight": 2.4, "pair_importance": 1.1},
            relation_events=[
                RelationEventDTO(
                    relation_event_id=101,
                    from_char="顾承渊",
                    to_char="苏映雪",
                    relation_type="盟友",
                    change_type="新建",
                    confidence=0.91,
                    directionality="directed",
                )
            ],
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
            "relation_events",
            "lifecycle_events",
        }
        assert payload["relation_events"][0]["relation_event_id"] == 101
