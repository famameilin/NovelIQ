"""
聚合指标集成测试。
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.metrics.aggregate.computers import compute_narrative_structure_metrics
from src.metrics.aggregate.types import AnnotationData, TensionData


class TestComputeNarrativeStructureMetrics:
    def test_compute_narrative_structure_metrics_aligns_annotation_and_tension_by_chapter_id(self) -> None:
        annotation_data = AnnotationData(
            chapter_ids=[1, 2, 3],
            event_types=["铺垫", "转折", "冲突"],
            cliffhangers=[0, 1, 0],
            pivot_moments=[0, 1, 0],
            emotional_valences=[0, 0, 0],
        )
        tension_data = TensionData(
            chapter_ids=[1, 2, 3],
            tension_composite_scores=[0.1, None, 0.9],
            positions=[0.0, 0.5, 1.0],
        )

        result = compute_narrative_structure_metrics(annotation_data, tension_data)

        # 章 2 张力 None 被对齐丢弃 → 结构类指标小样本返回 null；
        # 叙事功能占比分母为全部有效标注章节（3 章），不随张力交集收缩
        assert round(result["chapter_narrative_function_share_铺垫"], 6) == round(1 / 3, 6)
        assert round(result["chapter_narrative_function_share_冲突"], 6) == round(1 / 3, 6)
        assert round(result["chapter_narrative_function_share_转折"], 6) == round(1 / 3, 6)
        assert result["dominant_climax_pos"] is None
        assert result["act1_ratio"] is None
        assert result["climax_spacing"] is None
