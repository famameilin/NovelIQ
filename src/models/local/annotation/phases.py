"""
说明: Phase1/Phase2标注逻辑
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.models.local.annotation.messages import (
    _build_annotation_messages_v2,
    _build_foreshadowing_messages,
)
from src.models.local.parser import parse_active_entities

if TYPE_CHECKING:
    from src.rag.evidence_types import EvidenceBundle


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
) -> list[dict[str, Any]]:
    """
    构建Phase1消息
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
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
    evidence_bundle: EvidenceBundle | None = None,
    include_evidence_blocks: bool = False,
) -> list[dict[str, Any]]:
    """
    构建Phase2消息

    修改时间: 2026-04-30
    任务: annotation 静态检查收口
    修改原因: Phase2 prompt 已收口为当前 chunk + 活跃 setup 池，
              旧的 prev_chunk_text 槽位不再属于底层 builder 合同。
    """
    return _build_foreshadowing_messages(
        text=text,
        prev_chunk_summary=prev_chunk_summary,
        chunk_id=chunk_id,
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
        evidence_bundle=evidence_bundle,
        include_evidence_blocks=include_evidence_blocks,
    )


def build_validation_sources(
    text: str,
    active_entities: str | None = None,
    alias_map: dict[str, str] | None = None,
    evidence_bundle: EvidenceBundle | None = None,
) -> dict[str, Any]:
    """
    构建验证来源字典
    """
    return {
        "text": text,
        "active_entities": parse_active_entities(active_entities),
        "alias_map": alias_map or {},
        "evidence_bundle": evidence_bundle,
    }
