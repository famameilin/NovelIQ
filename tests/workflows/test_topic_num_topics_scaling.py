"""N2：num_topics 按训练文档数缩放的纯函数测试（无需数据库）。"""

from __future__ import annotations

from src.workflows.topic import resolve_num_topics

_MIN = 3
_MAX = 25
_DIVISOR = 30


def test_default_scaling_scales_with_valid_doc_count() -> None:
    # 600 篇有效文档 → 600 // 30 = 20 个主题
    result = resolve_num_topics(
        None,
        600,
        min_topics=_MIN,
        max_topics=_MAX,
        scaling_divisor=_DIVISOR,
    )
    assert result == 20


def test_default_scaling_clamps_to_min() -> None:
    # 30 篇以下 → 1//30=0 → 下限 3，避免短书退化成单主题
    result = resolve_num_topics(
        None,
        30,
        min_topics=_MIN,
        max_topics=_MAX,
        scaling_divisor=_DIVISOR,
    )
    assert result == 3


def test_default_scaling_clamps_to_max() -> None:
    # 1200 篇 → 40 → 上限 25，长书不再无限增加主题
    result = resolve_num_topics(
        None,
        1200,
        min_topics=_MIN,
        max_topics=_MAX,
        scaling_divisor=_DIVISOR,
    )
    assert result == 25


def test_explicit_num_topics_overrides_scaling() -> None:
    # 显式指定时直接透传，不做缩放与截断
    result = resolve_num_topics(
        18,
        1200,
        min_topics=_MIN,
        max_topics=_MAX,
        scaling_divisor=_DIVISOR,
    )
    assert result == 18


def test_zero_valid_docs_returns_min_topics() -> None:
    result = resolve_num_topics(
        None,
        0,
        min_topics=_MIN,
        max_topics=_MAX,
        scaling_divisor=_DIVISOR,
    )
    assert result == _MIN