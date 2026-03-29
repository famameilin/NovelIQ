"""
检查点保存和加载

创建时间: 2026-03-27
创建者: TraeAI
任务: disambiguation-module-split
说明: 从 disambiguation.py 拆分，包含检查点相关函数

修改时间: 2026-03-28
修改者: TraeAI
任务: consolidate-codebase-architecture
修改内容: 禁止静默吞异常，数据格式错误时抛出 ValueError
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import text

from src.models.local.disambiguation import DisambiguationState

if TYPE_CHECKING:
    pass

DisambigStateSnapshot = dict[str, dict[str, str]]


def _assert_checkpoint_schema(conn) -> None:
    """确保 disambig_checkpoint 已包含图投影阶段所需列。"""
    required_columns = {
        "last_annotated_chunk",
        "last_projected_chunk",
        "projection_interval",
    }
    rows = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'disambig_checkpoint'
            """
        )
    ).fetchall()
    existing_columns = {str(row[0]) for row in rows}
    missing = sorted(required_columns - existing_columns)
    if missing:
        missing_text = ", ".join(missing)
        raise RuntimeError(
            "disambig_checkpoint schema is outdated, missing columns: "
            f"{missing_text}. Run scripts/db/migrate_graph_projection_schema.py first."
        )


def _save_disambig_checkpoint_state(
    conn,
    run_id: str,
    state: DisambiguationState,
    last_annotated_chunk: int | None = None,
    last_projected_chunk: int | None = None,
    projection_interval: int | None = None,
) -> None:
    """
    保存消歧检查点
    
    创建时间: 2026-03-27
    创建者: TraeAI
    任务: disambiguation-state-three-layer
    说明: 保存完整的 DisambiguationState 到数据库
    """
    _assert_checkpoint_schema(conn)
    state_dict = state.to_dict()
    params = {
        "run_id": run_id,
        "state_json": json.dumps(state_dict),
        "updated_at": time.time(),
        "entity_relations": json.dumps(list(state.pending_relations)) if state.pending_relations else None,
        "disambig_states": None,
        "last_annotated_chunk": last_annotated_chunk,
        "last_projected_chunk": last_projected_chunk,
        "projection_interval": projection_interval,
    }
    conn.execute(
        text("""
        INSERT INTO disambig_checkpoint (
            run_id,
            alias_map,
            updated_at,
            entity_relations,
            disambig_states,
            last_annotated_chunk,
            last_projected_chunk,
            projection_interval
        )
        VALUES (
            :run_id,
            :state_json,
            :updated_at,
            :entity_relations,
            :disambig_states,
            :last_annotated_chunk,
            :last_projected_chunk,
            :projection_interval
        )
        ON CONFLICT (run_id) DO UPDATE SET
            alias_map = EXCLUDED.alias_map,
            updated_at = EXCLUDED.updated_at,
            entity_relations = EXCLUDED.entity_relations,
            disambig_states = EXCLUDED.disambig_states,
            last_annotated_chunk = COALESCE(EXCLUDED.last_annotated_chunk, disambig_checkpoint.last_annotated_chunk),
            last_projected_chunk = COALESCE(EXCLUDED.last_projected_chunk, disambig_checkpoint.last_projected_chunk),
            projection_interval = COALESCE(EXCLUDED.projection_interval, disambig_checkpoint.projection_interval)
    """),
        params,
    )
    conn.commit()
    logger.debug(
        f"disambig checkpoint saved: {len(state.discovered_names)} discovered, "
        f"{len(state.known_canonical_names)} canonicals, {len(state.alias_merges)} merges"
    )


def _load_disambig_checkpoint_state(conn, run_id: str) -> DisambiguationState:
    """
    加载消歧检查点
    
    创建时间: 2026-03-27
    创建者: TraeAI
    任务: disambiguation-state-three-layer
    说明: 从数据库加载完整的 DisambiguationState

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: consolidate-codebase-architecture
    修改内容: 禁止静默吞异常，数据格式错误时抛出 ValueError
    
    Returns:
        DisambiguationState: 完整的消歧状态

    Raises:
        ValueError: checkpoint 数据格式无效
    """
    result = conn.execute(
        text("SELECT alias_map, entity_relations FROM disambig_checkpoint WHERE run_id = :run_id"),
        {"run_id": run_id},
    ).fetchone()

    if not result or not result[0]:
        return DisambiguationState.empty()

    raw_data = json.loads(result[0])

    if not isinstance(raw_data, dict):
        raise ValueError(
            f"Invalid checkpoint data format for run_id={run_id}: "
            f"expected dict, got {type(raw_data).__name__}"
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


def load_disambig_checkpoint_metadata(conn, run_id: str) -> dict[str, int | None]:
    result = conn.execute(
        text(
            """
            SELECT last_annotated_chunk, last_projected_chunk, projection_interval
            FROM disambig_checkpoint
            WHERE run_id = :run_id
            """
        ),
        {"run_id": run_id},
    ).fetchone()
    if not result:
        return {
            "last_annotated_chunk": None,
            "last_projected_chunk": None,
            "projection_interval": None,
        }
    return {
        "last_annotated_chunk": result[0],
        "last_projected_chunk": result[1],
        "projection_interval": result[2],
    }
