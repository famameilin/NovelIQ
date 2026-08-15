"""
实体注册管理模块

说明: 管理活跃实体的上下文查询和提示词格式化
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.storage.repositories import GraphRepository


def format_entities_for_prompt(entities: list[dict[str, Any]]) -> str:
    """将实体列表格式化为提示词字符串"""
    if not entities:
        return ""

    lines = ["【近期活跃角色】"]
    for entity in entities:
        name = entity.get("name", "")
        role = entity.get("role", "")
        action = entity.get("last_action", "")
        emotion = entity.get("last_emotion", "")
        score = entity.get("emotion_score", 0)

        if role:
            line = f"{name}（{role}）"
        else:
            line = name

        if action or emotion:
            parts = []
            if action:
                parts.append(action)
            if emotion:
                if isinstance(score, int) and score != 0:
                    parts.append(f"{emotion}（{score}）")
                else:
                    parts.append(emotion)
            line += "：" + "；".join(parts)

        lines.append(line)

    return "\n".join(lines)


def _normalize_active_entity_row(row: Any) -> dict[str, Any] | None:
    """
    统一规范化 GraphRepository 返回的实体行
    """
    if isinstance(row, dict):
        name = row.get("name")
        if not name:
            return None
        return {
            "chunk_id": row.get("chunk_id"),
            "name": name,
            "role": row.get("role", ""),
            "last_action": row.get("last_action", ""),
            "last_emotion": row.get("last_emotion", ""),
            "emotion_score": row.get("emotion_score", 0),
        }

    name = getattr(row, "name", None)
    if not name:
        return None
    return {
        # 2026-08-15：dataclass 行（EntitySnapshotRow）的章锚点字段已改名
        # last_seen_chapter，chunk_id 属改名残留；按属性存在性回退取值，
        # 避免 dataclass 分支恒返回 None 的潜伏陷阱
        "chunk_id": getattr(row, "chunk_id", None)
        if hasattr(row, "chunk_id")
        else getattr(row, "last_seen_chapter", None),
        "name": name,
        "role": getattr(row, "role", "") or "",
        "last_action": getattr(row, "last_action", "") or "",
        "last_emotion": getattr(row, "last_emotion", "") or "",
        "emotion_score": getattr(row, "emotion_score", 0) or 0,
    }


def get_active_entities(
    graph_repo: GraphRepository,
    run_id: str,
    current_chunk_id: int,
    lookback: int = 10,
) -> list[dict[str, Any]]:
    """获取活跃实体列表（按名称去重，保留最新；仅保留 status 为 active 的实体）

    状态存于实体 state 字典，缺省视为 active（与 authority 服务口径一致）。
    """
    minimum_chunk_id = max(0, current_chunk_id - lookback)
    rows = [
        {
            "chunk_id": row.last_seen_chapter,
            "name": row.name,
            "role": row.state.get("role_function", ""),
            "last_action": row.state.get("action", ""),
            "last_emotion": row.state.get("emotion", ""),
            "emotion_score": row.state.get("emotion_score", 0),
        }
        for row in graph_repo.fetch_latest_entities(run_id)
        if minimum_chunk_id <= row.last_seen_chapter <= current_chunk_id
        and (row.state.get("status") or "active") == "active"
    ]

    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        normalized = _normalize_active_entity_row(row)
        if normalized is None:
            continue
        name = normalized["name"]
        # 2026-08-14 D9：保留 last_seen_chunk 最新者。此前 fetch_latest_entities
        # 按 entity_id 升序，首个同名行被保留，与"保留最新"注释承诺相反
        existing = seen.get(name)
        if existing is None or (normalized.get("chunk_id") or 0) > (existing.get("chunk_id") or 0):
            seen[name] = normalized

    return list(seen.values())
