"""伏笔回收预期计算防回归测试（2026-10-16 全库 3NF 改造）

伏笔根属性随不可变声明行保存（payoff_likelihood 是唯一属性，strength 为读
投影）；预期沿真实声明与原文证据计算，不再向旧事件行写 strength/status。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.event_trees.models import BoundEvent
from src.event_trees.read.foreshadowing import calculate_foreshadow_expectation
from src.fact_graph.vocabulary import Confidence
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import (
    add_annotation_source,
    add_declaration,
    first_paragraph,
)


def _create_foreshadow_root(
    session,
    *,
    run_id: str,
    payoff_likelihood: str | None,
    is_foreshadowing_root: bool = True,
    chapter_id: int = 1,
) -> str:
    """经真实标注来源链写入一条伏笔根声明（属性随声明行）"""
    record_id, _execution_id = add_annotation_source(session, run_id, chapter_id)
    return add_declaration(
        session,
        record_id=record_id,
        paragraph=first_paragraph(session, run_id, chapter_id=chapter_id),
        phrase="顾霜身份",
        title="顾霜身份成谜",
        is_foreshadowing_root=is_foreshadowing_root,
        payoff_likelihood=payoff_likelihood,
    )


def test_calculate_expectation_accepts_all_strength_levels(db_session) -> None:
    """high/medium/low 三档 payoff_likelihood 均不抛 KeyError。"""
    for likelihood in (Confidence.HIGH.value, Confidence.MEDIUM.value, Confidence.LOW.value):
        _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"])
        _create_foreshadow_root(db_session, run_id=run_id, payoff_likelihood=likelihood)
        db_session.commit()
        result = calculate_foreshadow_expectation(db_session, run_id)
        assert result is not None
        assert 0.0 <= result <= 1.0


def test_calculate_expectation_low_scores_below_medium(db_session) -> None:
    """payoff_likelihood 三档在回收预期上有真实梯度。"""
    results: dict[str, float] = {}
    for likelihood in (Confidence.HIGH.value, Confidence.MEDIUM.value, Confidence.LOW.value):
        _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"])
        _create_foreshadow_root(db_session, run_id=run_id, payoff_likelihood=likelihood)
        db_session.commit()
        result = calculate_foreshadow_expectation(db_session, run_id)
        assert result is not None
        results[likelihood] = result

    assert results[Confidence.LOW.value] < results[Confidence.MEDIUM.value]
    assert results[Confidence.MEDIUM.value] < results[Confidence.HIGH.value]


def test_formal_event_rejects_invalid_foreshadowing_confidence() -> None:
    """P3：伏笔枚举非法值直接 raise，不再降级为 unknown。"""
    with pytest.raises(ValidationError):
        BoundEvent(
            declaration_id="decl-root",
            node_id="decl-root",
            tree_id="tree-root",
            cause_role="root",
            title="埋设悬念",
            problem="悬念能否成立",
            summary="埋设悬念",
            event_type="行动",
            status="ongoing",
            description="埋设悬念",
            is_foreshadow_setup=True,
            payoff_likelihood="certain",
        )


def test_calculate_expectation_returns_none_when_all_evidence_missing(db_session) -> None:
    """P3：payoff_likelihood 全缺失时返回 None，不输出伪分。"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"])
    _create_foreshadow_root(db_session, run_id=run_id, payoff_likelihood=None)
    db_session.commit()

    result = calculate_foreshadow_expectation(db_session, run_id)
    assert result is None


def test_calculate_expectation_returns_none_without_threads(db_session) -> None:
    """无伏笔根声明时返回 None。"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"])
    result = calculate_foreshadow_expectation(db_session, run_id)
    assert result is None


def test_non_foreshadowing_declaration_does_not_score(db_session) -> None:
    """非伏笔声明即使带属性也不参与伏笔预期。"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"])
    _create_foreshadow_root(
        db_session,
        run_id=run_id,
        payoff_likelihood="high",
        is_foreshadowing_root=False,
    )
    db_session.commit()
    assert calculate_foreshadow_expectation(db_session, run_id) is None
