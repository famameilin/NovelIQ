"""preprocess_helpers 风格指标单元测试（2026-08-13 P2-4）"""

from __future__ import annotations

import pytest

from src.chunking.chunker import Chunk
from src.workflows.preprocess_helpers import _compute_chunk_style_metrics


def _chunk(text: str, index: int = 0) -> Chunk:
    return Chunk(index=index, start=0, end=len(text), text=text, chapter_id=1)


def test_chunk_style_metrics_computes_tension_densities() -> None:
    """战斗/感叹/问句密度由 rhythm_metrics.tension_proxy 计算而非硬编码 0"""
    style = _compute_chunk_style_metrics(
        _chunk("他拔剑怒喝！谁人敢挡？"),
        ["他", "拔剑", "怒喝", "谁人", "敢挡"],
        sensory_terms=[],
        function_words=[],
        semantic_categories={},
        imagery_terms=[],
        fight_terms={"拔剑": 1.0},
    )

    assert style.fight_density > 0.0
    assert style.exclaim_density > 0.0
    assert style.question_density > 0.0
    # tension_proxy 按自身分词统计 token 数，三个密度共享同一分母
    assert style.exclaim_density == pytest.approx(style.question_density)


def test_chunk_style_metrics_zero_densities_without_signals() -> None:
    """无战斗词条/感叹/问号时三个密度为 0（保持原有字段类型 float）"""
    style = _compute_chunk_style_metrics(
        _chunk("平静的开端。"),
        ["平静", "的", "开端"],
        sensory_terms=[],
        function_words=[],
        semantic_categories={},
        imagery_terms=[],
        fight_terms={},
    )

    assert style.fight_density == 0.0
    assert style.exclaim_density == 0.0
    assert style.question_density == 0.0
    assert isinstance(style.fight_density, float)
    assert isinstance(style.exclaim_density, float)
    assert isinstance(style.question_density, float)


def test_chunk_style_metrics_default_fight_terms_empty() -> None:
    """fight_terms 缺省为空 dict：感叹/问号仍正常计算，战斗密度为 0"""
    style = _compute_chunk_style_metrics(
        _chunk("竟然！真的吗？"),
        ["竟然", "真的", "吗"],
        sensory_terms=[],
        function_words=[],
        semantic_categories={},
        imagery_terms=[],
    )

    assert style.fight_density == 0.0
    assert style.exclaim_density > 0.0
    assert style.question_density > 0.0
