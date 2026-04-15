"""
测试 results_converters 模块

创建时间: 2026-03-13
创建者: TraeAI
任务: 测试结果转换器

修改时间: 2026-04-05
修改者: TraeAI
任务: 移动废弃测试
修改内容: 移除 culture_stats 相关测试（功能已废弃），移动到 deprecated/tests/api/
"""
import pytest

from src.api.routes.results_converters import (
    AGGREGATE_METRIC_CONTRACT_FIELDS,
    _convert_style_stats,
    build_aggregate_metrics_contract,
    validate_aggregate_metrics_contract,
)
from src.metrics.aggregate import AggregateResult


def test_convert_style_stats_tone_distribution_default_empty_dict() -> None:
    result = AggregateResult(language_style={"vocab_breadth": 0.42})

    style_stats = _convert_style_stats(result)

    assert style_stats is not None
    assert style_stats.tone_distribution == {}


def test_build_aggregate_metrics_contract_keeps_fixed_non_graph_keys() -> None:
    result = AggregateResult(
        narrative_structure={"act1_ratio": 0.2},
        emotion_curve={"positive_ratio": 0.4},
        character_relations={"network_density": 0.3},
        language_style={"tone_distribution": {"冷峻": 1.0}},
    )

    aggregate_metrics = build_aggregate_metrics_contract(result)

    assert tuple(aggregate_metrics.keys()) == AGGREGATE_METRIC_CONTRACT_FIELDS
    assert aggregate_metrics["narrative_structure"] == {
        "act1_ratio": 0.2,
        "act2_ratio": None,
        "act3_ratio": None,
        "climax_spacing": None,
        "middle_collapse_index": None,
        "event_density": None,
        "cliffhanger_rate": None,
        "climax_count": None,
        "climax_positions": None,
        "climax_heights": None,
        "peak_escalation": None,
        "dominant_climax_pos": None,
    }
    assert "graph_summary" not in aggregate_metrics
    assert "graph_quality_report" not in aggregate_metrics


def test_validate_aggregate_metrics_contract_rejects_graph_fields() -> None:
    with pytest.raises(ValueError, match="aggregate_metrics must not include graph-owned fields: graph_summary"):
        validate_aggregate_metrics_contract(
            {
                "narrative_structure": None,
                "emotion_stats": None,
                "character_stats": None,
                "style_stats": None,
                "culture_stats": None,
                "graph_summary": {},
            }
        )
