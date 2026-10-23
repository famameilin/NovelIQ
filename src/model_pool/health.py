"""模型健康分：按回合成功率、近期失败、token 花费、耗时和回合数加权，低于阈值不参与选举"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field

DEFAULT_SCORE = 100.0
MIN_SELECT_SCORE = 60.0
RECENT_WINDOW_SECONDS = 30 * 60
TOKEN_TOTAL_BASELINE = 2_000_000.0
TOKEN_TURN_BASELINE = 20_000.0
TIME_TURN_BASELINE_MS = 30_000.0
STABLE_TURNS = 50.0
IDLE_POINTS_PER_MINUTE = 1.0
MAX_IDLE_BONUS = 30.0
MAX_TURN_RECORDS = 1000

WEIGHTS = {
    "total_success": 0.05,
    "recent_success": 0.20,
    "recent_failure": 0.45,
    "total_token": 0.05,
    "avg_token": 0.05,
    "recent_token": 0.05,
    "time": 0.10,
    "turns": 0.05,
}


@dataclass(frozen=True, slots=True)
class TurnRecord:
    at: float
    success: bool
    tokens: int
    model_ms: float


@dataclass
class ModelRecord:
    turns: deque[TurnRecord] = field(default_factory=lambda: deque(maxlen=MAX_TURN_RECORDS))
    total_turns: int = 0
    success_total: int = 0
    failure_total: int = 0
    tokens_total: int = 0
    model_ms_total: float = 0.0
    last_turn_at: float | None = None


class ModelHealth:
    """进程内模型健康分，按模型累计回合事实；读取分数时结算时间窗与空闲加分"""

    def __init__(self) -> None:
        self._records: dict[str, ModelRecord] = {}

    def record_turn(self, model_id: str, *, success: bool, tokens: int = 0, model_ms: float = 0.0) -> None:
        """记录一次物理模型请求的结果、用量和耗时"""
        if not model_id or model_id == "unknown":
            return
        now = time.monotonic()
        record = self._records.setdefault(model_id, ModelRecord())
        record.turns.append(
            TurnRecord(at=now, success=success, tokens=max(0, int(tokens)), model_ms=max(0.0, float(model_ms)))
        )
        record.total_turns += 1
        record.success_total += int(success)
        record.failure_total += int(not success)
        record.tokens_total += max(0, int(tokens))
        record.model_ms_total += max(0.0, float(model_ms))
        record.last_turn_at = now

    def score(self, model_id: str, *, now: float | None = None) -> float:
        """返回模型当前健康分，未出现过的模型按未扣分处理"""
        record = self._records.get(model_id)
        if record is None:
            return DEFAULT_SCORE
        return self._score(record, time.monotonic() if now is None else now)

    def scores(self, model_ids: Iterable[str] | None = None) -> dict[str, float]:
        """一次结算多个模型的分数，缺失模型按未扣分处理"""
        now = time.monotonic()
        ids = set(model_ids or ()) | set(self._records)
        return {
            model_id: self._score(self._records[model_id], now) if model_id in self._records else DEFAULT_SCORE
            for model_id in ids
        }

    def eligible(self, model_id: str, *, now: float | None = None) -> bool:
        """健康分达到选举阈值"""
        return self.score(model_id, now=now) >= MIN_SELECT_SCORE

    def stats(self, model_id: str) -> dict[str, float | int | bool | None]:
        """供日志排查的模型回合摘要"""
        record = self._records.get(model_id)
        if record is None:
            return {"score": DEFAULT_SCORE, "total_turns": 0, "success_total": 0, "failure_total": 0,
                    "tokens_total": 0, "last_turn_at": None}
        now = time.monotonic()
        recent = self._recent(record, now)
        return {
            "score": self._score(record, now),
            "total_turns": record.total_turns,
            "success_total": record.success_total,
            "failure_total": record.failure_total,
            "recent_turns": len(recent),
            "recent_success": sum(1 for item in recent if item.success),
            "recent_failure": sum(1 for item in recent if not item.success),
            "recent_tokens": sum(item.tokens for item in recent),
            "tokens_total": record.tokens_total,
            "last_turn_at": record.last_turn_at,
        }

    def reset(self, model_ids: Iterable[str] | None = None) -> None:
        """清空健康账本，供测试隔离"""
        if model_ids is None:
            self._records.clear()
            return
        for model_id in model_ids:
            self._records.pop(model_id, None)

    @staticmethod
    def _recent(record: ModelRecord, now: float) -> list[TurnRecord]:
        cutoff = now - RECENT_WINDOW_SECONDS
        return [item for item in record.turns if item.at >= cutoff]

    def _score(self, record: ModelRecord, now: float) -> float:
        recent = self._recent(record, now)
        total_attempts = record.success_total + record.failure_total
        total_success = record.success_total / total_attempts if total_attempts else 1.0
        recent_attempts = len(recent)
        recent_successes = sum(1 for item in recent if item.success)
        recent_failures = recent_attempts - recent_successes
        recent_success = recent_successes / recent_attempts if recent_attempts else 1.0
        recent_failure = 1.0 - (recent_failures / recent_attempts if recent_attempts else 0.0)
        total_token = 1.0 / (1.0 + record.tokens_total / TOKEN_TOTAL_BASELINE)
        avg_tokens = record.tokens_total / record.total_turns if record.total_turns else 0.0
        avg_token = 1.0 / (1.0 + avg_tokens / TOKEN_TURN_BASELINE)
        recent_avg_tokens = sum(item.tokens for item in recent) / recent_attempts if recent_attempts else 0.0
        recent_token = 1.0 / (1.0 + recent_avg_tokens / TOKEN_TURN_BASELINE)
        avg_ms = record.model_ms_total / record.total_turns if record.total_turns else 0.0
        time_score = 1.0 / (1.0 + avg_ms / TIME_TURN_BASELINE_MS)
        turns = min(1.0, record.total_turns / STABLE_TURNS)
        components = {
            "total_success": total_success,
            "recent_success": recent_success,
            "recent_failure": recent_failure,
            "total_token": total_token,
            "avg_token": avg_token,
            "recent_token": recent_token,
            "time": time_score,
            "turns": turns,
        }
        weighted = sum(WEIGHTS[key] * value for key, value in components.items()) * 100.0
        idle_minutes = max(0.0, now - record.last_turn_at) / 60.0 if record.last_turn_at is not None else 0.0
        idle_bonus = min(MAX_IDLE_BONUS, idle_minutes * IDLE_POINTS_PER_MINUTE)
        return round(min(100.0, max(0.0, weighted + idle_bonus)), 1)


MODEL_HEALTH = ModelHealth()
