"""模型健康分：回合事实加权、阈值筛选与自然恢复"""

from __future__ import annotations

import time

from src.model_pool.health import MIN_SELECT_SCORE, MODEL_HEALTH, ModelHealth


def _record_many(health: ModelHealth, *, success: bool, turns: int, tokens: int = 0, model_ms: float = 0.0) -> None:
    for _ in range(turns):
        health.record_turn("model", success=success, tokens=tokens, model_ms=model_ms)


def test_unknown_model_starts_eligible() -> None:
    assert MODEL_HEALTH.score("unseen") == 100
    assert MODEL_HEALTH.eligible("unseen")


def test_failed_turn_drops_below_threshold() -> None:
    health = ModelHealth()
    health.record_turn("model", success=False)
    assert health.score("model") < MIN_SELECT_SCORE
    assert not health.eligible("model")


def test_successful_turns_raise_score() -> None:
    health = ModelHealth()
    _record_many(health, success=True, turns=10)
    assert health.score("model") > 90
    assert health.eligible("model")


def test_recent_success_offsets_old_failures() -> None:
    health = ModelHealth()
    _record_many(health, success=False, turns=5)
    for _ in range(20):
        health.record_turn("model", success=True)
    assert health.eligible("model")


def test_idle_time_restores_score() -> None:
    health = ModelHealth()
    health.record_turn("model", success=False)
    failed_at = time.monotonic()
    initial = health.score("model", now=failed_at)
    assert initial < MIN_SELECT_SCORE
    assert health.score("model", now=failed_at + 25 * 60) >= initial + 20


def test_recent_failures_age_out_of_window() -> None:
    health = ModelHealth()
    health.record_turn("model", success=False)
    failed_at = time.monotonic()
    assert health.score("model", now=failed_at + 31 * 60) >= MIN_SELECT_SCORE


def test_token_spend_lowers_score() -> None:
    cheap = ModelHealth()
    expensive = ModelHealth()
    _record_many(cheap, success=True, turns=10, tokens=100, model_ms=1000)
    _record_many(expensive, success=True, turns=10, tokens=60_000, model_ms=60_000)
    assert cheap.score("model") > expensive.score("model")


def test_reset_clears_model_record() -> None:
    health = ModelHealth()
    health.record_turn("model", success=False)
    health.reset(["model"])
    assert health.score("model") == 100
