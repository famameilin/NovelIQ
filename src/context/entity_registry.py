"""
实体注册管理模块

创建时间: 2025-03-12
创建者: TraeAI
任务: 实体注册管理

修改历史:
- 2026-03-11: 添加 alias_map 参数，修复自环问题 (Claude)
- 2026-03-14: 使用 EntityRepository 接口重构 (TraeAI)
- 2026-03-16: 修复 emotion_score 类型转换 (TraeAI)

说明: 管理实体注册表，处理人物名称、角色、情感等信息的注册。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.storage.repositories import EntityRepository


EMOTION_SCORE_MAPPING: dict[str, int] = {
    "strong_positive": 2,
    "mild_positive": 1,
    "neutral": 0,
    "mild_negative": -1,
    "strong_negative": -2,
}


def _convert_emotion_score(score: Any) -> int:
    """将 emotion_score 转换为整数"""
    if score is None:
        return 0
    if isinstance(score, int):
        return score
    if isinstance(score, str):
        return EMOTION_SCORE_MAPPING.get(score, 0)
    return 0


def update_entity_registry(
    entity_repo: EntityRepository,
    run_id: str,
    chunk_id: int,
    characters: list[Any],
    alias_map: dict[str, str] | None = None,
) -> None:
    """更新实体注册表"""
    alias_map = alias_map or {}
    for char in characters:
        if hasattr(char, "name"):
            name = char.name
            role = getattr(char, "role_function", None)
            action = getattr(char, "action", None)
            score = getattr(char, "emotion_score", None)
        else:
            name = char["name"]
            role = char["role_function"]
            action = char["action"]
            score = char["emotion_score"]

        canonical = alias_map.get(name, name)

        entity_repo.insert_entity_registry(
            chunk_id=chunk_id,
            name=canonical,
            role=role or "",
            last_action=action or "",
            last_emotion="",
            emotion_score=_convert_emotion_score(score),
            run_id=run_id,
        )


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


def get_active_entities(
    entity_repo: EntityRepository,
    run_id: str,
    current_chunk_id: int,
    lookback: int = 10,
) -> list[dict[str, Any]]:
    """获取活跃实体列表（按名称去重，保留最新）"""
    rows = entity_repo.fetch_active_entities(current_chunk_id, lookback, run_id)

    # 使用字典去重，保留每个名称的最新记录
    seen = {}
    for row in rows:
        name = row[1]
        if name not in seen:
            seen[name] = {
                "chunk_id": row[0],
                "name": name,
                "role": row[2],
                "last_action": row[3],
                "last_emotion": row[4],
                "emotion_score": row[5],
            }

    return list(seen.values())
