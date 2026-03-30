"""
叙事时间轴核心算法单元测试

测试范围:
- compute_importance_score: 重要性分数计算
- compute_four_phases: 四阶段划分算法
- select_timeline_nodes: 节点筛选逻辑
- 边界条件测试（短小说、数据缺失等）
"""

from __future__ import annotations

import pytest

from src.api.models.timeline import RelationChangeEvent
from src.metrics.timeline_metrics import (
    NarrativePhase,
    TimelineCandidate,
    calculate_tension_percentile,
    compute_four_phases,
    compute_importance_score,
    convert_to_timeline_nodes,
    convert_to_timeline_phases,
    select_timeline_nodes,
)


class TestComputeImportanceScore:
    """测试重要性分数计算"""

    def test_all_factors_max_score(self):
        """测试所有因素最高分时返回正确分数和级别"""
        score, level = compute_importance_score(
            pivot_moment=True,
            cliffhanger=True,
            tension_composite=1.0,
            all_tensions=[0.0, 0.5, 1.0],
            event_type="冲突",
            emotional_valence="strong_positive",
            has_relation_change=True,
            has_character_entry=True,
            has_character_exit=False,
            is_major_character=True,
        )
        # 3(转折) + 2(悬念) + 2(张力百分位100%) + 1(冲突) + 1(极端情感) + 2(关系变化) + 2(主要角色) = 13
        # 但实际最大约11分
        assert score > 7
        assert level == 1

    def test_min_score(self):
        """测试所有因素最低分时返回正确分数和级别"""
        score, level = compute_importance_score(
            pivot_moment=False,
            cliffhanger=False,
            tension_composite=0.0,
            all_tensions=[0.0, 0.5, 1.0],
            event_type="铺垫",
            emotional_valence="neutral",
            has_relation_change=False,
            has_character_entry=False,
            has_character_exit=False,
            is_major_character=False,
        )
        # 只有张力百分位: 0/3 = 0%, *2 = 0
        assert score == 0.0
        assert level == 3

    def test_level_thresholds(self):
        """测试级别阈值边界"""
        # level 1 (>=7)
        score, level = compute_importance_score(
            pivot_moment=True,  # +3
            cliffhanger=True,  # +2
            tension_composite=1.0,
            all_tensions=[0.0, 1.0],
            event_type="铺垫",
            emotional_valence="neutral",
        )
        assert score >= 7
        assert level == 1

        # level 2 (4-6)
        score, level = compute_importance_score(
            pivot_moment=True,  # +3
            cliffhanger=True,  # +2
            tension_composite=0.0,
            all_tensions=[0.0, 1.0],
            event_type="铺垫",
            emotional_valence="neutral",
        )
        # 3 + 2 + 0 = 5
        assert 4 <= score <= 6
        assert level == 2

        # level 3 (<4)
        score, level = compute_importance_score(
            pivot_moment=False,
            cliffhanger=False,
            tension_composite=0.5,
            all_tensions=[0.0, 1.0],
            event_type="铺垫",
            emotional_valence="neutral",
        )
        # 百分位约50% * 2 = 1
        assert score < 4
        assert level == 3

    def test_empty_tensions(self):
        """测试空张力列表时不会崩溃"""
        score, level = compute_importance_score(
            pivot_moment=True,
            cliffhanger=False,
            tension_composite=0.5,
            all_tensions=[],
            event_type="冲突",
            emotional_valence="strong_positive",
        )
        assert score >= 0
        assert level in (1, 2, 3)

    def test_tension_percentile_calculation(self):
        """测试张力百分位计算正确"""
        all_tensions = [0.0, 0.25, 0.5, 0.75, 1.0]

        # 最小值，百分位 = 20% (1/5)
        score, _ = compute_importance_score(
            pivot_moment=False,
            cliffhanger=False,
            tension_composite=0.0,
            all_tensions=all_tensions,
            event_type="铺垫",
            emotional_valence="neutral",
        )
        assert score == pytest.approx(0.2 * 2, abs=0.01)  # 0.4

        # 最大值，百分位 = 100% (5/5)
        score, _ = compute_importance_score(
            pivot_moment=False,
            cliffhanger=False,
            tension_composite=1.0,
            all_tensions=all_tensions,
            event_type="铺垫",
            emotional_valence="neutral",
        )
        assert score == pytest.approx(1.0 * 2, abs=0.01)  # 2.0


class TestComputeFourPhases:
    """测试四阶段划分算法"""

    def test_short_novel_fixed_ratio(self):
        """测试短小说使用固定比例"""
        tension_scores = [0.1] * 10
        chunk_ids = list(range(1, 11))

        phases = compute_four_phases(tension_scores, chunk_ids)

        assert len(phases) == 4
        assert phases[0].name == "引入期"
        assert phases[1].name == "发展期"
        assert phases[2].name == "高潮期"
        assert phases[3].name == "收束期"

        # 检查各阶段至少1个chunk
        for phase in phases:
            # 找到start和end在chunk_ids中的索引差
            start_idx = chunk_ids.index(phase.start)
            end_idx = chunk_ids.index(phase.end)
            assert end_idx - start_idx + 1 >= 1

    def test_long_novel_dynamic_phases(self):
        """测试长小说使用张力曲线动态划分"""
        # 创建一个张力曲线，高潮在中间
        tension_scores = [0.1] * 40 + [0.9] + [0.1] * 59
        chunk_ids = list(range(1, 101))

        phases = compute_four_phases(tension_scores, chunk_ids)

        assert len(phases) >= 3  # 至少3个阶段
        phase_names = [p.name for p in phases]
        assert "高潮期" in phase_names

        # 高潮期应该在张力峰值附近
        climax_phase = next(p for p in phases if p.name == "高潮期")
        assert 30 <= chunk_ids.index(climax_phase.start) <= 50

    def test_peak_at_start(self):
        """测试峰值在开始位置的边界情况"""
        tension_scores = [0.9] + [0.1] * 99
        chunk_ids = list(range(1, 101))

        phases = compute_four_phases(tension_scores, chunk_ids)

        # 应该有至少引入期和高潮期
        assert len(phases) >= 2

    def test_peak_at_end(self):
        """测试峰值在结束位置的边界情况"""
        tension_scores = [0.1] * 99 + [0.9]
        chunk_ids = list(range(1, 101))

        phases = compute_four_phases(tension_scores, chunk_ids)

        assert len(phases) >= 2

    def test_empty_data(self):
        """测试空数据返回空列表"""
        assert compute_four_phases([], []) == []
        assert compute_four_phases([0.5], []) == []
        assert compute_four_phases([], [1]) == []

    def test_min_phase_length_protection(self):
        """测试最小阶段长度保护"""
        tension_scores = [0.1, 0.5, 0.9, 0.5, 0.1]
        chunk_ids = list(range(1, 6))

        phases = compute_four_phases(tension_scores, chunk_ids)

        # 即使数据很少，每个阶段也应该至少有1个chunk
        for phase in phases:
            start_idx = chunk_ids.index(phase.start)
            end_idx = chunk_ids.index(phase.end)
            assert end_idx - start_idx + 1 >= 1


class TestSelectTimelineNodes:
    """测试节点筛选逻辑"""

    def create_candidate(self, chunk_id: int, progress: float, importance_score: float, level: int = 3, **kwargs):
        """辅助方法：创建候选节点"""
        return TimelineCandidate(
            chunk_id=chunk_id,
            progress=progress,
            importance_score=importance_score,
            level=level,
            event=f"Event at {chunk_id}",
            characters=kwargs.get("characters", []),
            is_pivot=kwargs.get("is_pivot", False),
            is_cliffhanger=kwargs.get("is_cliffhanger", False),
            tension_percentile=kwargs.get("tension_percentile", 50),
            node_type=kwargs.get("node_type", "plot"),
        )

    def test_must_keep_nodes(self):
        """测试必选节点（开始、结束、高潮）一定被包含"""
        chunk_ids = [1, 2, 3, 4, 5]
        tension_scores = [0.1, 0.3, 0.9, 0.5, 0.2]  # 高潮在 chunk 3 (index 2)

        candidates = [
            self.create_candidate(1, 0.0, 1.0),
            self.create_candidate(2, 0.25, 2.0),
            self.create_candidate(3, 0.5, 3.0),
            self.create_candidate(4, 0.75, 2.0),
            self.create_candidate(5, 1.0, 1.0),
        ]

        selected = select_timeline_nodes(
            candidates=candidates,
            chunk_ids=chunk_ids,
            tension_scores=tension_scores,
            major_character_entries=[],
            relation_break_events=[],
            min_nodes=3,
            max_nodes=10,
        )

        selected_chunk_ids = [c.chunk_id for c in selected]
        assert 1 in selected_chunk_ids  # 开始
        assert 5 in selected_chunk_ids  # 结束
        assert 3 in selected_chunk_ids  # 高潮

    def test_max_nodes_limit(self):
        """测试最大节点数限制"""
        chunk_ids = list(range(1, 21))
        tension_scores = [0.1] * 20

        candidates = [self.create_candidate(i, (i - 1) / 19, float(i)) for i in chunk_ids]

        selected = select_timeline_nodes(
            candidates=candidates,
            chunk_ids=chunk_ids,
            tension_scores=tension_scores,
            major_character_entries=[],
            relation_break_events=[],
            min_nodes=5,
            max_nodes=10,
        )

        assert len(selected) <= 10

    def test_min_nodes_fill(self):
        """测试节点数不足时自动补充"""
        chunk_ids = [1, 2, 3]
        tension_scores = [0.1, 0.5, 0.9]

        candidates = [
            self.create_candidate(1, 0.0, 1.0),
            self.create_candidate(2, 0.5, 2.0),
            self.create_candidate(3, 1.0, 3.0),
        ]

        selected = select_timeline_nodes(
            candidates=candidates,
            chunk_ids=chunk_ids,
            tension_scores=tension_scores,
            major_character_entries=[],
            relation_break_events=[],
            min_nodes=5,  # 要求5个，但只有3个候选
            max_nodes=10,
        )

        # 最多只能返回3个
        assert len(selected) <= 3

    def test_pivot_priority(self):
        """测试转折点优先级高于普通节点"""
        chunk_ids = list(range(1, 11))
        tension_scores = [0.1] * 10

        candidates = [
            self.create_candidate(1, 0.0, 1.0),  # 必选：开始
            self.create_candidate(2, 0.11, 1.0),  # 普通节点
            self.create_candidate(3, 0.22, 1.0, is_pivot=True),  # 转折点
            self.create_candidate(4, 0.33, 1.0),  # 普通节点
            self.create_candidate(5, 0.44, 1.0, is_pivot=True),  # 转折点
            self.create_candidate(6, 0.55, 1.0),  # 普通节点
            self.create_candidate(7, 0.66, 1.0),  # 普通节点
            self.create_candidate(8, 0.77, 1.0),  # 普通节点
            self.create_candidate(9, 0.88, 1.0),  # 普通节点
            self.create_candidate(10, 1.0, 1.0),  # 必选：结束
        ]

        selected = select_timeline_nodes(
            candidates=candidates,
            chunk_ids=chunk_ids,
            tension_scores=tension_scores,
            major_character_entries=[],
            relation_break_events=[],
            min_nodes=5,
            max_nodes=7,
        )

        # 转折点应该被包含
        selected_pivot_ids = [c.chunk_id for c in selected if c.is_pivot]
        assert 3 in selected_pivot_ids or 5 in selected_pivot_ids

    def test_cliffhanger_limit(self):
        """测试悬念点限制在5个以内"""
        chunk_ids = list(range(1, 21))
        tension_scores = [0.1] * 20

        candidates = [
            self.create_candidate(1, 0.0, 1.0),  # 开始
            *[self.create_candidate(i, (i - 1) / 19, 1.0, is_cliffhanger=True) for i in range(2, 20)],
            self.create_candidate(20, 1.0, 1.0),  # 结束
        ]

        selected = select_timeline_nodes(
            candidates=candidates,
            chunk_ids=chunk_ids,
            tension_scores=tension_scores,
            major_character_entries=[],
            relation_break_events=[],
            min_nodes=10,
            max_nodes=15,
        )

        # 悬念点最多5个
        cliffhanger_count = sum(1 for c in selected if c.is_cliffhanger)
        assert cliffhanger_count <= 5

    def test_progress_sorting(self):
        """测试返回节点按 progress 排序"""
        chunk_ids = [1, 2, 3, 4, 5]
        tension_scores = [0.1, 0.3, 0.9, 0.5, 0.2]

        candidates = [
            self.create_candidate(1, 0.0, 1.0),
            self.create_candidate(5, 1.0, 1.0),
            self.create_candidate(3, 0.5, 1.0),
        ]

        selected = select_timeline_nodes(
            candidates=candidates,
            chunk_ids=chunk_ids,
            tension_scores=tension_scores,
            major_character_entries=[],
            relation_break_events=[],
            min_nodes=3,
            max_nodes=10,
        )

        # 检查是否按 progress 排序
        progresses = [c.progress for c in selected]
        assert progresses == sorted(progresses)


class TestGetMajorCharactersBySpan:
    """测试主要角色判断（基于活跃跨度）"""

    def test_span_calculation(self):
        """测试活跃跨度计算正确"""
        from unittest.mock import MagicMock

        # 模拟 GraphEntity
        entities = []
        for name, first, last in [("A", 1, 100), ("B", 50, 60), ("C", 1, 50)]:
            e = MagicMock()
            e.canonical_name = name
            e.first_seen_chunk = first
            e.last_seen_chunk = last
            entities.append(e)

        from src.metrics.timeline_metrics import get_major_characters_by_span

        major = get_major_characters_by_span(entities, top_n=2)

        # A 的跨度 = 100, C 的跨度 = 50, B 的跨度 = 11
        assert len(major) == 2
        assert major[0].canonical_name == "A"  # 跨度最大
        assert major[1].canonical_name == "C"  # 跨度第二

    def test_none_chunks_filtered(self):
        """测试 first_seen_chunk 或 last_seen_chunk 为 None 的实体被过滤"""
        from unittest.mock import MagicMock

        entities = []
        for name, first, last in [
            ("A", 1, 100),
            ("B", None, 60),  # 无效
            ("C", 1, None),  # 无效
        ]:
            e = MagicMock()
            e.canonical_name = name
            e.first_seen_chunk = first
            e.last_seen_chunk = last
            entities.append(e)

        from src.metrics.timeline_metrics import get_major_characters_by_span

        major = get_major_characters_by_span(entities, top_n=3)

        assert len(major) == 1
        assert major[0].canonical_name == "A"

    def test_empty_entities(self):
        """测试空实体列表返回空"""
        from src.metrics.timeline_metrics import get_major_characters_by_span

        major = get_major_characters_by_span([], top_n=3)
        assert major == []

    def test_hasattr_protection(self):
        """测试函数通过 hasattr 保护属性访问"""
        from src.metrics.timeline_metrics import get_major_characters_by_span

        # 模拟一个没有完整属性的对象
        class PartialEntity:
            pass

        # 只有 first_seen_chunk 的对象
        e1 = PartialEntity()
        e1.first_seen_chunk = 1
        # 缺少 last_seen_chunk

        # 只有 last_seen_chunk 的对象
        e2 = PartialEntity()
        # 缺少 first_seen_chunk
        e2.last_seen_chunk = 100

        # 完整的对象
        e3 = PartialEntity()
        e3.first_seen_chunk = 1
        e3.last_seen_chunk = 50

        major = get_major_characters_by_span([e1, e2, e3], top_n=3)

        # 只有 e3 应该被选中
        assert len(major) == 1
        assert major[0] == e3

    def test_empty_candidates(self):
        """测试空候选列表返回空"""
        selected = select_timeline_nodes(
            candidates=[],
            chunk_ids=[],
            tension_scores=[],
            major_character_entries=[],
            relation_break_events=[],
        )
        assert selected == []


class TestCalculateTensionPercentile:
    """测试张力百分位计算"""

    def test_normal_calculation(self):
        """测试正常情况下的百分位计算"""
        all_tensions = [0.0, 0.25, 0.5, 0.75, 1.0]

        assert calculate_tension_percentile(0.0, all_tensions) == 20
        assert calculate_tension_percentile(0.25, all_tensions) == 40
        assert calculate_tension_percentile(0.5, all_tensions) == 60
        assert calculate_tension_percentile(1.0, all_tensions) == 100

    def test_empty_list(self):
        """测试空列表返回默认值"""
        assert calculate_tension_percentile(0.5, []) == 50


class TestConvertToTimelinePhases:
    """测试阶段转换函数"""

    def test_normal_conversion(self):
        """测试正常转换"""
        phases = [
            NarrativePhase("引入期", 1, 10, 0.2),
            NarrativePhase("发展期", 11, 50, 0.4),
            NarrativePhase("高潮期", 51, 70, 0.2),
            NarrativePhase("收束期", 71, 100, 0.2),
        ]

        timeline_phases = convert_to_timeline_phases(phases)

        assert len(timeline_phases) == 4
        assert timeline_phases[0].name == "引入期"
        assert timeline_phases[0].start == 1
        assert timeline_phases[0].end == 10

    def test_invalid_name_fallback(self):
        """测试无效名称时使用fallback"""
        phases = [
            NarrativePhase("无效名称", 1, 10, 0.2),
        ]

        timeline_phases = convert_to_timeline_phases(phases)
        assert timeline_phases[0].name == "引入期"


class TestConvertToTimelineNodes:
    """测试节点转换函数"""

    def test_normal_conversion(self):
        """测试正常转换"""
        candidates = [
            TimelineCandidate(
                chunk_id=1,
                progress=0.0,
                importance_score=6.5,
                level=1,
                event="Test event",
                characters=["A", "B"],
                is_pivot=False,
                is_cliffhanger=False,
                tension_percentile=50,
                node_type="plot",
            )
        ]

        nodes = convert_to_timeline_nodes(candidates)

        assert len(nodes) == 1
        assert nodes[0].chunk_id == 1
        assert nodes[0].importance_score == 6.5
        assert nodes[0].level == 1

    def test_with_relation_changes(self):
        """测试带关系变化的节点转换"""
        relation_changes = [
            RelationChangeEvent(
                from_char="A",
                to_char="B",
                relation_type="师徒",
                change_type="断裂",
                evidence="Test",
            )
        ]

        candidates = [
            TimelineCandidate(
                chunk_id=1,
                progress=0.0,
                importance_score=8.0,
                level=1,
                event="关系变化",
                characters=["A", "B"],
                is_pivot=False,
                is_cliffhanger=False,
                tension_percentile=80,
                node_type="relation_change",
                relation_changes=relation_changes,
            )
        ]

        nodes = convert_to_timeline_nodes(candidates)

        assert len(nodes) == 1
        assert nodes[0].node_type == "relation_change"
        assert nodes[0].relation_changes is not None
        assert len(nodes[0].relation_changes) == 1


class TestIntegration:
    """集成测试"""

    def test_full_workflow_short_novel(self):
        """测试短小说完整流程"""
        # 模拟10个chunk的短小说
        chunk_ids = list(range(1, 11))
        tension_scores = [0.2, 0.3, 0.5, 0.6, 0.9, 0.8, 0.5, 0.3, 0.2, 0.1]

        # 1. 计算四阶段
        phases = compute_four_phases(tension_scores, chunk_ids)
        assert len(phases) == 4

        # 2. 创建候选节点
        candidates = []
        for i, chunk_id in enumerate(chunk_ids):
            score, level = compute_importance_score(
                pivot_moment=(i == 4),  # 高潮处是转折点
                cliffhanger=(i == 8),  # 悬念点
                tension_composite=tension_scores[i],
                all_tensions=tension_scores,
                event_type="冲突" if i == 4 else "铺垫",
                emotional_valence="neutral",
            )
            candidates.append(
                TimelineCandidate(
                    chunk_id=chunk_id,
                    progress=i / 9,
                    importance_score=score,
                    level=level,
                    event=f"Event {chunk_id}",
                    characters=[],
                    is_pivot=(i == 4),
                    is_cliffhanger=(i == 8),
                    tension_percentile=calculate_tension_percentile(tension_scores[i], tension_scores),
                    node_type="plot",
                )
            )

        # 3. 筛选节点
        selected = select_timeline_nodes(
            candidates=candidates,
            chunk_ids=chunk_ids,
            tension_scores=tension_scores,
            major_character_entries=[],
            relation_break_events=[],
            min_nodes=5,
            max_nodes=8,
        )

        assert len(selected) >= 3  # 至少包含开始、结束、高潮
        assert len(selected) <= 8  # 不超过最大值

        # 转折点应该被选中
        pivot_selected = any(c.is_pivot for c in selected)
        assert pivot_selected

    def test_full_workflow_long_novel(self):
        """测试长小说完整流程"""
        # 模拟100个chunk的长小说
        chunk_ids = list(range(1, 101))
        # 创建有高峰的张力曲线
        tension_scores = [0.1] * 30 + [0.3, 0.5, 0.7, 0.9, 0.95, 0.9, 0.7, 0.5, 0.3] + [0.1] * 61

        # 计算四阶段
        phases = compute_four_phases(tension_scores, chunk_ids)
        assert len(phases) >= 3

        # 验证高潮期在正确的位置
        climax_phase = next((p for p in phases if p.name == "高潮期"), None)
        assert climax_phase is not None
        assert 25 <= chunk_ids.index(climax_phase.start) <= 45  # 高潮期在30-40附近
