"""
测试 results_converters 模块

创建时间: 2026-03-13
任务: 测试结果转换器

修改时间: 2026-04-05
任务: 移动废弃测试
修改内容: 移除 culture_stats 相关测试（功能已废弃）
"""

import pytest

from src.api.routes.results_converters import (
    _convert_style_stats,
    build_aggregate_metrics_contract,
    validate_aggregate_metrics_contract,
)
from src.metrics.aggregate import AggregateResult


def test_convert_style_stats_tone_distribution_default_empty_dict() -> None:
    result = AggregateResult(language_style={"string_token_diversity": 0.42})

    style_stats = _convert_style_stats(result)

    assert style_stats is not None
    assert style_stats.tone_distribution == {}


def test_build_aggregate_metrics_contract_renames_aggregate_keys() -> None:
    """2026-08-14 重命名（§13.3）：章节标签占比/pivot 率/关系变化频率使用新键名"""
    result = AggregateResult(
        narrative_structure={"chapter_narrative_function_share_冲突": 0.5},
        emotion_curve={"chapter_pivot_rate": 0.25},
        character_relations={"relation_change_per_10k_chars": 3.0},
        language_style={"tone_distribution": {"冷峻": 1.0}},
    )

    aggregate_metrics = build_aggregate_metrics_contract(result)

    narrative_structure = aggregate_metrics["narrative_structure"]
    assert narrative_structure["chapter_narrative_function_share"] == {"冲突": 0.5}
    assert "event_density" not in narrative_structure
    emotion_stats = aggregate_metrics["emotion_stats"]
    assert emotion_stats["chapter_pivot_rate"] == 0.25
    assert "pivot_moment_density" not in emotion_stats
    character_stats = aggregate_metrics["character_stats"]
    assert character_stats["relation_change_per_10k_chars"] == 3.0
    assert "relation_change_freq" not in character_stats


def test_validate_aggregate_metrics_contract_rejects_graph_fields() -> None:
    with pytest.raises(ValueError, match="aggregate_metrics must not include graph-owned fields: graph_summary"):
        validate_aggregate_metrics_contract(
            {
                "narrative_structure": None,
                "emotion_stats": None,
                "character_stats": None,
                "style_stats": None,
                "graph_summary": {},
            }
        )
