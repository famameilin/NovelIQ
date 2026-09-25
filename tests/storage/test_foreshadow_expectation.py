"""伏笔回收预期计算防回归测试"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.annotation.schema import Confidence, ResolvedCase
from src.storage.models import EventNode
from src.storage.repositories.annotation.repository import AnnotationRepository
from tests.support.chapter_annotation_helpers import create_run_with_chunks, persist_chapter_annotation


def _create_foreshadow_root(
    session: Session,
    *,
    run_id: str,
    strength: str | None,
    status: str = "open",
    payoff_likelihood: str | None = "high",
    chapter_id: int = 1,
) -> str:
    """2026-09-13 经标注持久化创建伏笔树根事件并补齐 strength/status。"""
    persist_chapter_annotation(
        session,
        run_id=run_id,
        chapter_id=chapter_id,
        events=[
            {
                "description": "顾霜立誓",
                "participants": ["顾霜"],
                "anchor_paragraph_ids": [0],
                "isforeshadowing": True,
                "payoff_likelihood": payoff_likelihood or "medium",
            },
        ],
    )
    root = session.execute(
        select(EventNode).where(EventNode.run_id == run_id, EventNode.is_foreshadowing_root.is_(True))
    ).scalars().one()
    root.strength = strength
    root.foreshadowing_status = status
    root.payoff_likelihood = payoff_likelihood
    session.flush()
    return root.event_id


def test_calculate_expectation_accepts_all_strength_levels(db_session) -> None:
    """high/medium/low 三档 strength 均不抛 KeyError。"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"])

    for strength in (Confidence.HIGH.value, Confidence.MEDIUM.value, Confidence.LOW.value):
        _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"])
        _create_foreshadow_root(db_session, run_id=run_id, strength=strength)
        db_session.commit()
        result = AnnotationRepository(db_session).calculate_foreshadow_expectation(run_id)
        assert result is not None
        assert 0.0 <= result <= 1.0


def test_calculate_expectation_low_scores_below_medium(db_session) -> None:
    """strength 三档在回收预期上有真实梯度。"""
    results: dict[str, float] = {}
    for strength in (Confidence.HIGH.value, Confidence.MEDIUM.value, Confidence.LOW.value):
        _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"])
        _create_foreshadow_root(db_session, run_id=run_id, strength=strength)
        db_session.commit()
        result = AnnotationRepository(db_session).calculate_foreshadow_expectation(run_id)
        assert result is not None
        results[strength] = result

    assert results[Confidence.LOW.value] < results[Confidence.MEDIUM.value]
    assert results[Confidence.MEDIUM.value] < results[Confidence.HIGH.value]


def test_resolved_case_rejects_invalid_foreshadowing_enums() -> None:
    """P3：伏笔枚举非法值直接 raise，不再降级为 unknown。"""
    with pytest.raises(ValidationError):
        ResolvedCase(
            case_id="case-1",
            action="foreshadowing",
            type="foreshadowing_suspect",
            reason="任意字符串不应静默入库",
            target_key="target-1",
            target_ref={"chunk_id": 1},
            foreshadowing_action="reinforce",
            foreshadowing_root_event_id="evt-root",
            foreshadowing_event_id="evt-bind",
            payoff_likelihood="certain",
            strength="mega",
        )


def test_calculate_expectation_returns_none_when_all_evidence_missing(db_session) -> None:
    """P3：payoff_likelihood/strength 全缺失时返回 None，不输出伪分。"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"])
    _create_foreshadow_root(
        db_session,
        run_id=run_id,
        strength=None,
        payoff_likelihood=None,
    )
    db_session.commit()

    result = AnnotationRepository(db_session).calculate_foreshadow_expectation(run_id)
    assert result is None


def test_calculate_expectation_returns_none_without_threads(db_session) -> None:
    """无伏笔树根时返回 None。"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"])
    result = AnnotationRepository(db_session).calculate_foreshadow_expectation(run_id)
    assert result is None
