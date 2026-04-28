"""
检查点保存和加载

仅保存/加载 DisambiguationState，不存储图投影进度等元数据
"""

from __future__ import annotations

import json
import time

from loguru import logger
from sqlalchemy import text

from src.models.local.disambiguation import DisambiguationState


def _save_disambig_checkpoint(
    conn,
    run_id: str,
    state: DisambiguationState,
) -> None:
    """保存消歧检查点到数据库（upsert）"""
    state_dict = state.to_dict()
    conn.execute(
        text("""
        INSERT INTO disambig_checkpoint (run_id, state_json, updated_at)
        VALUES (:run_id, :state_json, :updated_at)
        ON CONFLICT (run_id) DO UPDATE SET
            state_json = EXCLUDED.state_json,
            updated_at = EXCLUDED.updated_at
    """),
        {
            "run_id": run_id,
            "state_json": json.dumps(state_dict, ensure_ascii=False),
            "updated_at": time.time(),
        },
    )
    conn.commit()
    logger.debug(
        f"disambig checkpoint saved: {len(state.discovered_names)} discovered, "
        f"{len(state.known_canonical_names)} canonicals, {len(state.alias_merges)} merges"
    )


def _load_disambig_checkpoint(
    conn,
    run_id: str,
) -> DisambiguationState:
    """
    从数据库加载消歧检查点

    Returns:
        DisambiguationState: 完整的消歧状态

    Raises:
        ValueError: checkpoint 数据格式无效
    """
    result = conn.execute(
        text("SELECT state_json FROM disambig_checkpoint WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).fetchone()

    if not result or not result[0]:
        return DisambiguationState.empty()

    raw_data = json.loads(result[0])

    if not isinstance(raw_data, dict):
        raise ValueError(
            f"Invalid checkpoint data format for run_id={run_id}: expected dict, got {type(raw_data).__name__}"
        )

    if "discovered_names" not in raw_data or "known_canonical_names" not in raw_data:
        raise ValueError(
            f"Missing required fields in checkpoint data for run_id={run_id}: "
            "'discovered_names' and 'known_canonical_names'"
        )

    state = DisambiguationState.from_dict(raw_data)
    logger.info(
        f"disambig checkpoint loaded: "
        f"{len(state.discovered_names)} discovered, "
        f"{len(state.known_canonical_names)} canonicals, "
        f"{len(state.alias_merges)} merges"
    )
    return state
