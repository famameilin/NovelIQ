"报告弧线评分与人物名单引用的正式角色目录"

from __future__ import annotations

import unicodedata

from src.storage import Storage


def normalize_character_name(name: str) -> str:
    "角色名身份比较沿用 NFC/strip/casefold 合同"
    return unicodedata.normalize("NFC", name).strip().casefold()


def character_names(session: Storage, run_id: str) -> dict[str, str]:
    """本 run 正式角色的比较键到规范名映射"""
    rows = session.reads.agents_diagnosis_persistence_character_entity_ids_1(run_id)
    return {normalize_character_name(row.canonical_name): row.canonical_name for row in rows}


def character_entity_ids(session: Storage, run_id: str) -> dict[str, str]:
    """本 run 正式角色的比较键到实体 ID 映射"""
    rows = session.reads.agents_diagnosis_persistence_character_entity_ids_1(run_id)
    return {normalize_character_name(row.canonical_name): row.entity_id for row in rows}
