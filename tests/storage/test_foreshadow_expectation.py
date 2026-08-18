"""伏笔回收预期计算防回归测试"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.agents.annotation.schema import Confidence, PayoffLikelihood, ResolvedCase, SetupStatus
from src.storage.models import ForeshadowingThread, ForeshadowingThreadHit
from src.storage.repositories.annotation.repository import (
    _EXPECTATION_BASE_SCORE_BY_PAYOFF,
    _EXPECTATION_STATUS_BONUS,
    _EXPECTATION_STATUS_WEIGHT,
    _EXPECTATION_STRENGTH_BONUS,
    _EXPECTATION_STRENGTH_WEIGHT,
    AnnotationRepository,
)
from tests.support.chapter_annotation_helpers import create_run_with_chunks


def _create_thread_with_hit(
    session: Session,
    *,
    run_id: str,
    strength: str | None,
    status: str = "open",
    payoff_likelihood: str | None = "high",
    confidence: str = "high",
    chapter_id: int = 1,
) -> str:
    """插入带命中记录的伏笔线程并返回 setup_id。"""
    setup_id = f"setup-{strength}-{status}-{payoff_likelihood}-{uuid.uuid4().hex[:8]}"[:36]
    setup_event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"event:{setup_id}"))
    session.add(
        ForeshadowingThread(
            setup_id=setup_id,
            run_id=run_id,
            first_chapter_id=chapter_id,
            last_chapter_id=chapter_id,
            setup_summary=f"测试伏笔 {setup_id}",
            foreshadowing_type="物件",
            setup_kind="异常物件",
            expected_payoff_family="主线",
            payoff_likelihood=payoff_likelihood,
            confidence=confidence,
            strength=strength,
            status=status,
            active=True,
            setup_event_id=setup_event_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    session.add(
        ForeshadowingThreadHit(
            setup_id=setup_id,
            run_id=run_id,
            chapter_id=chapter_id,
            anchor_text="测试锚点",
            is_new_setup=True,
            event_id=setup_event_id,
            created_at=datetime.now(UTC),
        )
    )
    session.flush()
    return setup_id


def test_calculate_expectation_accepts_all_strength_levels(db_session) -> None:
    """high/medium/low 三档 strength 均不抛 KeyError。"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"])

    for strength in (Confidence.HIGH.value, Confidence.MEDIUM.value, Confidence.LOW.value):
        _create_thread_with_hit(db_session, run_id=run_id, strength=strength)
    db_session.commit()

    result = AnnotationRepository(db_session).calculate_foreshadow_expectation(run_id)
    assert result is not None
    assert 0.0 <= result <= 1.0


def test_calculate_expectation_low_scores_below_medium(db_session) -> None:
    """strength 三档在回收预期上有真实梯度。"""
    results: dict[str, float] = {}
    for strength in (Confidence.HIGH.value, Confidence.MEDIUM.value, Confidence.LOW.value):
        _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"])
        _create_thread_with_hit(db_session, run_id=run_id, strength=strength)
        db_session.commit()
        result = AnnotationRepository(db_session).calculate_foreshadow_expectation(run_id)
        assert result is not None
        results[strength] = result

    assert results[Confidence.LOW.value] < results[Confidence.MEDIUM.value]
    assert results[Confidence.MEDIUM.value] < results[Confidence.HIGH.value]


def test_expectation_mappings_cover_enum_domains() -> None:
    """所有期望映射字典都完整覆盖对应枚举值。"""
    assert set(_EXPECTATION_BASE_SCORE_BY_PAYOFF) == {item.value for item in PayoffLikelihood}
    assert set(_EXPECTATION_STATUS_BONUS) == {item.value for item in SetupStatus}
    assert set(_EXPECTATION_STATUS_WEIGHT) == {item.value for item in SetupStatus}
    assert set(_EXPECTATION_STRENGTH_BONUS) == {item.value for item in Confidence}
    assert set(_EXPECTATION_STRENGTH_WEIGHT) == {item.value for item in Confidence}


def test_resolved_case_rejects_invalid_foreshadowing_enums() -> None:
    """P3：伏笔枚举非法值直接 raise，不再降级为 unknown。"""
    with pytest.raises(ValidationError, match="枚举漂移"):
        ResolvedCase(
            case_id="case-1",
            action="foreshadowing",
            type="foreshadowing_suspect",
            reason="任意字符串不应静默入库",
            target_key="target-1",
            target_ref={"setup_id": "setup-1", "chunk_id": 1},
            setup_status="已回收",
            payoff_likelihood="certain",
            strength="mega",
        )


def test_resolved_case_keeps_valid_foreshadowing_enums() -> None:
    """合法枚举值原样保留。"""
    resolved = ResolvedCase(
        case_id="case-1",
        action="foreshadowing",
        type="foreshadowing_suspect",
        reason="合法枚举",
        target_key="target-1",
        target_ref={"setup_id": "setup-1", "chunk_id": 1},
        setup_status="reinforced",
        payoff_likelihood="high",
        strength="low",
    )

    assert resolved.setup_status == "reinforced"
    assert resolved.payoff_likelihood == "high"
    assert resolved.strength == "low"


def test_calculate_expectation_returns_none_when_all_evidence_missing(db_session) -> None:
    """P3：payoff_likelihood/strength 全缺失时返回 None，不输出伪分。"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"])
    _create_thread_with_hit(
        db_session,
        run_id=run_id,
        strength=None,
        payoff_likelihood=None,
    )
    db_session.commit()

    result = AnnotationRepository(db_session).calculate_foreshadow_expectation(run_id)
    assert result is None


def test_calculate_expectation_returns_none_without_threads(db_session) -> None:
    """无伏笔线程时返回 None。"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜身份成谜"])
    result = AnnotationRepository(db_session).calculate_foreshadow_expectation(run_id)
    assert result is None
