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

from typing import TYPE_CHECKING, Any, Dict, List, Optional

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
    """将 emotion_score 转换为整数"""
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
