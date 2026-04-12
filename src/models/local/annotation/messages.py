"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 8 拆分annotation_client
说明: 消息构建相关方法

修改时间: 2026-03-23
修改者: TraeAI
任务: prompt-consolidation
修改内容: 移除旧版 prompt 导入
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.models.local.prompts import (
    FEW_SHOT_EXAMPLES_V2,
    FORESHADOWING_EXAMPLES,
    FORESHADOWING_SYSTEM_PROMPT,
    FORESHADOWING_USER_TEMPLATE,
    FORMAT_REQUIREMENTS_V2,
    SYSTEM_PROMPT_V2,
    USER_TEMPLATE_V2,
)
from src.models.local.annotation.evidence_renderer import render_annotation_evidence_blocks

if TYPE_CHECKING:
    from src.rag import EvidenceBundle


def _build_annotation_messages_v2(
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
    构建第一次调用（基础标注）的messages

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: refactor-phase1-identity-extraction
    修改内容: 移除 character_appearances 参数

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: simplify-phase1-prompt
    修改内容: 移除 prev_chunk_text 和 next_chunk_text 参数
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT_V2}]

    for example in FEW_SHOT_EXAMPLES_V2:
        messages.append({"role": "user", "content": example["user"]})
        messages.append({"role": "assistant", "content": example["assistant"]})

    alias_map_str = "{}"
    if alias_map:
        canonical_to_aliases: dict[str, list[str]] = {}
        for alias, canonical in alias_map.items():
            if canonical not in canonical_to_aliases:
                canonical_to_aliases[canonical] = []
            canonical_to_aliases[canonical].append(alias)
        lines = []
        for canonical, aliases in canonical_to_aliases.items():
            alias_str = "、".join(aliases)
            lines.append(f"- {alias_str} → {canonical}")
        alias_map_str = "\n".join(lines)

    active_entities_str = active_entities or "[]"

    user_content = USER_TEMPLATE_V2.format(
        novel_title=novel_title or "未知",
        main_characters=main_characters or "",
        position_pct=position_pct or 0.0,
        chapter_id=chapter_id or 0,
        alias_map=alias_map_str,
        active_entities=active_entities_str,
        chunk_text=text,
    )

    user_content += "\n\n" + FORMAT_REQUIREMENTS_V2

    if chunk_id is not None:
        user_content += f"\n\n<Current_Chunk_ID>{chunk_id}</Current_Chunk_ID>"

    if evidence_bundle is not None:
        for block in render_annotation_evidence_blocks(evidence_bundle):
            user_content += f"\n\n{block}"
    elif disambig_context:
        user_content += f"\n\n{disambig_context}"

    messages.append({"role": "user", "content": user_content})
    return messages


def _build_foreshadowing_messages(
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
    构建第二次调用（伏笔分析）的messages

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分
    """
    messages = [{"role": "system", "content": FORESHADOWING_SYSTEM_PROMPT}]

    messages.append({"role": "user", "content": FORESHADOWING_EXAMPLES})

    user_content = FORESHADOWING_USER_TEMPLATE.format(
        novel_title=novel_title or "未知",
        main_characters=main_characters or "",
        position_pct=position_pct or 0.0,
        chapter_id=chapter_id or 0,
        prev_chunk_summary=prev_chunk_summary or "（无前文摘要）",
        prev_chunk_text=prev_chunk_text or "（无前文）",
        chunk_text=text,
        next_chunk_text=next_chunk_text or "（无后文）",
    )

    messages.append({"role": "user", "content": user_content})
    return messages
