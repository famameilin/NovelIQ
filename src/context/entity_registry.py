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
        "chunk_id": getattr(row, "chunk_id", None),
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
    """获取活跃实体列表（按名称去重，保留最新）"""
    rows = graph_repo.fetch_active_entities(current_chunk_id, lookback, run_id)

    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        normalized = _normalize_active_entity_row(row)
        if normalized is None:
            continue
        name = normalized["name"]
        if name not in seen:
            seen[name] = normalized

    return list(seen.values())
