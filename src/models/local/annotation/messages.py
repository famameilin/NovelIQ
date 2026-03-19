"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 8 拆分annotation_client
说明: 消息构建相关方法
"""

from __future__ import annotations

from typing import Dict, List

from src.models.local.prompts import (
    FEW_SHOT_EXAMPLES,
    FEW_SHOT_EXAMPLES_V2,
    FORESHADOWING_EXAMPLES,
    FORESHADOWING_SYSTEM_PROMPT,
    FORESHADOWING_USER_TEMPLATE,
    FORMAT_REQUIREMENTS,
    FORMAT_REQUIREMENTS_V2,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_V2,
    USER_TEMPLATE_V2,
)


def _build_messages(
    text: str,
    prev_summary: str | None = None,
    alias_map: Dict[str, str] | None = None,
    global_context: str | None = None,
    prev_chunk_text: str | None = None,
    active_entities: str | None = None,
    rag_evidence: str | None = None,
    known_aliases: str | None = None,
    next_chunk_text: str | None = None,
    chunk_id: int | None = None,
) -> List[dict]:
    """构建标注消息

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 统一字段命名，使用 prev_chunk_text 和 next_chunk_text
    """
    system_content = SYSTEM_PROMPT
    if global_context:
        system_content = f"{SYSTEM_PROMPT}\n\n{global_context}"
    messages = [{"role": "system", "content": system_content}]
    for example in FEW_SHOT_EXAMPLES:
        messages.append({"role": "user", "content": example["user"]})
        messages.append({"role": "assistant", "content": example["assistant"]})
    user_parts = []
    if prev_summary:
        user_parts.append(f"【前文摘要】\n{prev_summary}")
    if prev_chunk_text:
        user_parts.append(f"<Previous_Chunk>\n{prev_chunk_text}\n</Previous_Chunk>")
    if active_entities:
        user_parts.append(f"<Active_Entities>\n{active_entities}\n</Active_Entities>")
    if known_aliases:
        user_parts.append(known_aliases)
    if rag_evidence:
        user_parts.append(rag_evidence)
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
        alias_section = "【人物别名对照表】\n" + "\n".join(lines)
        alias_section += "\n请在输出 characters[].name 时，统一使用正式名（箭头右侧的名字）。"
        user_parts.append(alias_section)
    if next_chunk_text:
        user_parts.append(f"<Next_Chunk>\n{next_chunk_text}\n</Next_Chunk>")
    user_parts.append(f"【待分析文本】\n{text}")
    user_parts.append(FORMAT_REQUIREMENTS)
    if chunk_id is not None:
        user_parts.append(f"<Current_Chunk_ID>{chunk_id}</Current_Chunk_ID>")
    user_content = "\n\n".join(user_parts)
    messages.append({"role": "user", "content": user_content})
    return messages


def _build_annotation_messages_v2(
    text: str,
    alias_map: Dict[str, str] | None = None,
    chunk_id: int | None = None,
    prev_chunk_text: str | None = None,
    next_chunk_text: str | None = None,
    novel_title: str | None = None,
    main_characters: str | None = None,
    position_pct: float | None = None,
    chapter_id: int | None = None,
    active_entities: str | None = None,
) -> List[dict]:
    """
    构建第一次调用（基础标注）的messages

    创建时间: 2026-03-14
    创建者: TraeAI
    任务: Chunk 双次调用分析拆分
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
        prev_chunk_text=prev_chunk_text or "（无前文）",
        chunk_text=text,
        next_chunk_text=next_chunk_text or "（无后文）",
    )

    user_content += "\n\n" + FORMAT_REQUIREMENTS_V2

    if chunk_id is not None:
        user_content += f"\n\n<Current_Chunk_ID>{chunk_id}</Current_Chunk_ID>"

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
) -> List[dict]:
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
