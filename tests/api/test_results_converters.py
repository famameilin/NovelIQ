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
from src.api.routes.results_converters import _convert_style_stats
from src.metrics.aggregate import AggregateResult


def test_convert_style_stats_tone_distribution_default_empty_dict() -> None:
    result = AggregateResult(language_style={"vocab_breadth": 0.42})

    style_stats = _convert_style_stats(result)

    assert style_stats is not None
    assert style_stats.tone_distribution == {}
