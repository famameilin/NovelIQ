"""
Phase4: 关系事件抽取。

当前实现以轻量启发式为主，优先保证输出结构稳定、证据可追溯、
原始称呼不被改写；正式名绑定与图谱归一化在投影阶段完成。
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from src.models.local.schema import RelationChangeSnapshot

_RELATION_PATTERNS: list[tuple[str, str, tuple[str, ...]]] = [
    ("师徒", "新建", ("师父", "徒弟", "弟子", "收徒", "拜师")),
    ("敌对", "强化", ("敌人", "仇人", "仇敌", "死敌", "对峙", "交手", "杀意", "敌对")),
    ("盟友", "新建", ("盟友", "同盟", "联手", "并肩", "合作")),
    ("友情", "新建", ("朋友", "好友", "玩伴", "兄弟", "姐妹")),
    ("爱慕", "强化", ("喜欢", "爱慕", "心悦", "倾心", "相思")),
    ("家族", "新建", ("父亲", "母亲", "兄长", "姐姐", "妹妹", "弟弟", "家人", "族人")),
    ("利益", "新建", ("交易", "利益", "筹码", "合作条件")),
    ("主从", "新建", ("主人", "仆从", "属下", "手下", "下属", "听命")),
]

_CHANGE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("断裂", ("决裂", "反目", "断绝", "撕破脸")),
    ("弱化", ("疏远", "冷淡", "不再", "松动")),
    ("强化", ("更", "越发", "更加", "愈发", "加深")),
    ("新建", ("成为", "结为", "拜作", "认作")),
]


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？!?；;\n]+", text)
    return [part.strip() for part in parts if part and part.strip()]


def _find_present_names(sentence: str, known_characters: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for name in known_characters:
        if name and name in sentence and name not in seen:
            seen.append(name)
    return seen


def _detect_relation(sentence: str) -> tuple[str, str] | None:
    relation_type: str | None = None
    change_type = "新建"

    for candidate_type, default_change, keywords in _RELATION_PATTERNS:
        if any(keyword in sentence for keyword in keywords):
            relation_type = candidate_type
            change_type = default_change
            break

    if relation_type is None:
        return None

    for candidate_change, keywords in _CHANGE_PATTERNS:
        if any(keyword in sentence for keyword in keywords):
            change_type = candidate_change
            break

    return relation_type, change_type


def annotate_chunk_phase4(
    text: str,
    known_characters: list[str] | None = None,
    source_model: str | None = None,
) -> list[RelationChangeSnapshot]:
    sentences = _split_sentences(text)
    if not sentences or not known_characters:
        return []

    relations: list[RelationChangeSnapshot] = []
    seen_keys: set[tuple[str, str, str, str, str]] = set()

    for sentence in sentences:
        detected = _detect_relation(sentence)
        if detected is None:
            continue

        relation_type, change_type = detected
        present_names = _find_present_names(sentence, known_characters)
        if len(present_names) < 2:
            continue

        from_name = present_names[0]
        to_name = present_names[1]
        if from_name == to_name:
            continue

        key = (from_name, to_name, relation_type, change_type, sentence)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        relations.append(
            RelationChangeSnapshot(
                from_name=from_name,
                to_name=to_name,
                type=relation_type,
                change=change_type,
                evidence=sentence,
                confidence=0.65,
                source_model=source_model or "phase4-heuristic",
                projection_status="pending",
                directionality="symmetric" if relation_type in {"盟友", "友情", "家族"} else "directed",
            )
        )

    return relations
