"""所属领域的产物完整性查询，供恢复编排调用"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import (
    AnalysisOutput,
)


def _payload_has_valid_diagnosis_contract(payload: dict[str, Any]) -> bool:
    """2026-08-20 用于确认诊断产物包含完整焦点合同且能通过当前模型校验"""
    raw_focus_characters = payload.get("focus_characters")
    raw_main_characters = payload.get("main_characters")
    raw_core_cast = payload.get("core_cast")

    # 正式诊断必须有焦点结构和三组角色名单，只有旧字段的半成品行不算完成
    if (
        payload.get("focus_structure") not in {"single", "dual", "ensemble"}
        or not isinstance(raw_focus_characters, list)
        or not raw_focus_characters
        or not isinstance(raw_main_characters, list)
        or not raw_main_characters
        or not isinstance(raw_core_cast, list)
        or not raw_core_cast
    ):
        return False

    if not any(
        (
            payload.get("foreshadow_expectation") is not None,
            bool(payload.get("arc_scores")),
            bool(payload.get("genre_labels")),
            bool(payload.get("style_labels")),
            bool(payload.get("topic_labels")),
            payload.get("diagnosis") is not None,
            payload.get("value_logic_type") is not None,
            payload.get("value_logic_reason") is not None,
            payload.get("power_stance_score") is not None,
            payload.get("power_stance_reason") is not None,
            payload.get("common_people_dignity") is not None,
            payload.get("dignity_reason") is not None,
            payload.get("cultural_depth_score") is not None,
            payload.get("cultural_depth_reason") is not None,
            payload.get("narrative_arc_type") is not None,
            payload.get("theme_color") is not None,
        )
    ):
        return False

    return True


def has_diagnosis_data(session: Session, run_id: str) -> bool:
    """检查指定运行是否有诊断数据。Args: session/run_id；Returns: 是否存在。"""
    latest_row = session.execute(
        select(AnalysisOutput)
        .where(AnalysisOutput.run_id == run_id, AnalysisOutput.kind == "agent_analysis")
        .order_by(AnalysisOutput.created_at.desc(), AnalysisOutput.output_id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest_row is None:
        return False
    return _payload_has_valid_diagnosis_contract(latest_row.payload)
