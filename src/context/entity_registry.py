from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

"""
创建时间: 2025-03-12
创建者: TraeAI
任务: 实体注册管理

修改时间: 2026-03-11
修改者: Claude
任务: 自环问题修复
修改内容: 添加 alias_map 参数，将别名转换为正式名，避免同一人物的不同称呼被当作不同人物

修改时间: 2026-03-14
修改者: TraeAI
任务: metrics-repository-refactor
修改内容: 重构为使用 Repository 模式
- 使用 EntityRepository 接口
- 添加 run_id 参数支持

修改时间: 2026-03-16
修改者: TraeAI
任务: postgresql-migration-cleanup
修改内容: 修复 emotion_score 类型转换，将字符串类型转换为整数
"""

if TYPE_CHECKING:
    from src.storage.repositories import EntityRepository


EMOTION_SCORE_MAPPING: Dict[str, int] = {
    "strong_positive": 2,
    "mild_positive": 1,
    "neutral": 0,
    "mild_negative": -1,
    "strong_negative": -2,
}


def _convert_emotion_score(score: Any) -> int:
    """
    将 emotion_score 转换为整数

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: postgresql-migration-cleanup
    说明: 支持字符串类型（如 "neutral"）和整数类型的 emotion_score
    """
    if score is None:
        return 0
    if isinstance(score, int):
        return score
    if isinstance(score, str):
        return EMOTION_SCORE_MAPPING.get(score, 0)
    return 0


def update_entity_registry(
    entity_repo: "EntityRepository",
    run_id: str,
    chunk_id: int,
    characters: List[Any],
    alias_map: Optional[Dict[str, str]] = None,
) -> None:
    """
    更新实体注册表

    2026-03-11 自环问题修复任务 - Claude
    添加 alias_map 参数，将别名转换为正式名，避免同一人物的不同称呼被当作不同人物

    2026-03-14 修改 - TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 EntityRepository 接口，添加 run_id 参数
    """
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


def get_active_entities(
    entity_repo: "EntityRepository",
    run_id: str,
    current_chunk_id: int,
    lookback: int = 10,
) -> List[Dict[str, Any]]:
    """
    获取活跃实体列表

    2026-03-14 修改 - TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 EntityRepository 接口，添加 run_id 参数
    """
    rows = entity_repo.fetch_active_entities(current_chunk_id, lookback, run_id)
    seen = {}
    for row in rows:
        entity_id, name, role, last_action, last_emotion, emotion_score = row
        if name not in seen:
            seen[name] = {
                "entity_id": entity_id,
                "name": name,
                "role": role,
                "last_action": last_action,
                "last_emotion": last_emotion,
                "emotion_score": emotion_score,
            }
    return list(seen.values())


def format_entities_for_prompt(
    entities: List[Dict[str, Any]],
    alias_map: dict[str, str] | None = None,
) -> str:
    """
    格式化活跃实体列表为 Prompt 格式

    修改时间: 2026-03-12
    修改者: TraeAI
    任务: 优化 Active Entities 格式，只保留正式名
    修改内容: 添加 alias_map 参数，过滤别名，只保留正式名
    """
    if not entities:
        return ""

    alias_map = alias_map or {}
    canonical_names: set[str] = set()
    lines = ["【近期活跃角色】"]

    for entity in entities:
        name = entity["name"]
        canonical = alias_map.get(name, name)
        if canonical in canonical_names:
            continue
        canonical_names.add(canonical)

        role = entity["role"]
        last_action = entity["last_action"]
        last_emotion = entity["last_emotion"]
        emotion_score = entity["emotion_score"]
        lines.append(f"- {canonical}（{role}）：{last_action}；{last_emotion}（{emotion_score}）")

    return "\n".join(lines)
