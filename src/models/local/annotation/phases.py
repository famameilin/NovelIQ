"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 8 拆分annotation_client
说明: Phase1/Phase2标注逻辑

修改时间: 2026-03-29
修改者: TraeAI
任务: refactor-phase1-identity-extraction
修改内容: 移除 character_appearances 参数

修改时间: 2026-03-29
修改者: TraeAI
任务: simplify-phase1-prompt
修改内容: 移除 Phase1 的 prev_chunk_text 和 next_chunk_text 参数
"""

from __future__ import annotations

from src.models.local.annotation.messages import (
    _build_annotation_messages_v2,
    _build_foreshadowing_messages,
)
from src.models.local.parser import parse_active_entities
from src.rag import EvidenceBundle


def build_phase1_messages(
    text: str,
    alias_map: dict[str, str] | None = None,
    chunk_id: int | None = None,
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
    active_entities: str | None = None,
    disambig_context: str | None = None,
    evidence_bundle: EvidenceBundle | None = None,
) -> list[dict]:
    """
    构建Phase1消息

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - Task 8 拆分annotation_client

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: refactor-phase1-identity-extraction
    修改内容: 移除 character_appearances 参数

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: simplify-phase1-prompt
    修改内容: 移除 prev_chunk_text 和 next_chunk_text 参数
    """
    return _build_annotation_messages_v2(
        text=text,
        alias_map=alias_map,
        chunk_id=chunk_id,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
        active_entities=active_entities,
        disambig_context=disambig_context,
        evidence_bundle=evidence_bundle,
    )


def build_phase2_messages(
    text: str,
    prev_chunk_summary: str | None = None,
    chunk_id: int | None = None,
    prev_chunk_text: str | None = None,
    next_chunk_text: str | None = None,
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
) -> list[dict]:
    """
    构建Phase2消息

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - Task 8 拆分annotation_client
    """
    return _build_foreshadowing_messages(
        text=text,
        prev_chunk_summary=prev_chunk_summary,
        chunk_id=chunk_id,
        prev_chunk_text=prev_chunk_text,
        next_chunk_text=next_chunk_text,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
    )


def build_validation_sources(
    text: str,
    active_entities: str | None = None,
    alias_map: dict[str, str] | None = None,
) -> dict:
    """
    构建验证来源字典

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - Task 8 拆分annotation_client

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 统一字段命名，使用 prev_chunk_text 和 next_chunk_text

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: refactor-phase1-identity-extraction
    修改内容: 移除 character_appearances 参数

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: simplify-phase1-prompt
    修改内容: 移除 prev_chunk_text 和 next_chunk_text 参数
    """
    return {
        "text": text,
        "active_entities": parse_active_entities(active_entities),
        "alias_map": alias_map or {},
    }
