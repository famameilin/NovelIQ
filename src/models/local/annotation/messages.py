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

from src.models.local.annotation.evidence_renderer import (
    render_annotation_alias_map_text,
    render_annotation_evidence_blocks,
    render_annotation_prompt_blocks,
)
from src.models.local.prompts import (
    FEW_SHOT_EXAMPLES_V2,
    FORESHADOWING_EXAMPLES,
    FORESHADOWING_SYSTEM_PROMPT,
    FORESHADOWING_USER_TEMPLATE,
    FORMAT_REQUIREMENTS_V2,
    SYSTEM_PROMPT_V2,
    USER_TEMPLATE_V2,
)
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
    evidence_bundle=None,
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

    alias_map_str = render_annotation_alias_map_text(alias_map=alias_map, evidence_bundle=evidence_bundle)

    if evidence_bundle is not None:
        blocks = render_annotation_prompt_blocks(
            evidence_bundle,
            include_level1_alias_mappings=alias_map is None,
        )
        # 中文注释：EvidenceBundle 是新的主语义入口。
        # 兼容层字符串只在 bundle 没有产出对应 prompt block 时兜底，避免旧字段反向覆盖新设计。
        # 如果调用方显式给了 alias_map（包括空 dict），就不再把 bundle 里的 Level 1 别名裁决
        # 通过 disambig_context 反向注入，避免新旧入口共存时出现优先级错位。
        if blocks.active_entities is not None:
            active_entities = blocks.active_entities
        if blocks.disambig_context is not None:
            disambig_context = blocks.disambig_context

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

    if disambig_context:
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
    evidence_bundle=None,
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

    if evidence_bundle is not None:
        # 中文注释：Phase 2 只被动复用共享 evidence block，
        # 不再引入 narrative 专用的二次渲染协议，避免这轮收口任务继续外扩。
        evidence_sections = render_annotation_evidence_blocks(evidence_bundle)
        if evidence_sections:
            user_content += "\n\n" + "\n\n".join(evidence_sections)

    messages.append({"role": "user", "content": user_content})
    return messages
