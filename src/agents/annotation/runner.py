"""
标注 Agent 运行入口

- 单 chunk 运行：构建图 + 工具 + 身份记忆，产出合并标注结果
- 超长章节分派子代理：同一章节被切分的多个子 chunk 各自以独立 agent 会话
  （共享身份记忆）处理，state 携带同章节其余子块文本作为章节上下文
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from loguru import logger

from src.models.local.annotation.projectors.dialogue import build_dialogue_snapshots
from src.models.local.parser import build_annotation, parse_foreshadowing_result
from src.models.local.schema import (
    ForeshadowingResult,
    RelationChangeSnapshot,
)
from src.rag import NarrativeEvidenceService

from .graph import build_annotation_graph
from .memory import IdentityMemory
from .prompts import build_system_prompt
from .schema import MergedChunkAnnotation
from .tools import build_annotation_tools


@dataclass
class AnnotationChunkResult:
    """单 chunk 合并标注结果（可直接喂给存储层）"""

    annotation: Any
    foreshadowing: ForeshadowingResult | None = None
    dialogue_speakers: dict[int, list[str]] | None = None
    dialogues: list[tuple[int, str]] | None = None
    dialogue_tones: dict[int, str] | None = None
    dialogue_identity_clues: dict[int, str | None] | None = None
    dialogue_lengths: list[int] | None = None
    relations: list[RelationChangeSnapshot] | None = None


def _locate_dialogue_index(content: str, chunk_text: str, used_indices: set[int], next_index: int) -> int:
    """在 chunk 文本中定位对话原文位置，找不到时按顺序分配索引"""
    if content and content in chunk_text:
        position = chunk_text.find(content)
        # 用位置做稳定索引，避免同一文本重复出现时相互覆盖
        candidate = position + 1
        while candidate in used_indices:
            candidate += 1
        return candidate
    while next_index in used_indices:
        next_index += 1
    return next_index


def convert_merged_output(merged: MergedChunkAnnotation, chunk_text: str) -> AnnotationChunkResult:
    """将合并输出转换为存储层可消费的结果"""
    annotation_data = {
        "emotional_valence": merged.emotional_valence,
        "event_type": merged.event_type,
        "pivot_moment": merged.pivot_moment,
        "cliffhanger": merged.cliffhanger,
        "chunk_summary": merged.chunk_summary,
        "has_foreshadowing": merged.foreshadowing is not None and merged.foreshadowing.has_foreshadowing,
        "foreshadowing_type": merged.foreshadowing.foreshadowing_type if merged.foreshadowing else None,
        "foreshadowing_desc": merged.foreshadowing.anchor_text if merged.foreshadowing else "",
        "characters": [
            {
                "name": c.name,
                "role_function": c.role_function,
                "action": c.action,
                "action_type": c.action_type,
                "emotion_score": c.emotion_score,
            }
            for c in merged.characters
        ],
        "location_appearances": [
            {"raw_name": loc.raw_name, "location_type": loc.location_type}
            for loc in merged.location_appearances
        ],
    }
    annotation = build_annotation(annotation_data)

    foreshadowing: ForeshadowingResult | None = None
    if merged.foreshadowing is not None:
        foreshadowing_data = merged.foreshadowing.model_dump(mode="json")
        # 合并输出中 has_foreshadowing=true 即视为强伏笔（与旧 Phase2 合同一致）
        foreshadowing_data["is_strong_setup"] = bool(foreshadowing_data.get("has_foreshadowing", False))
        foreshadowing = parse_foreshadowing_result(foreshadowing_data)

    dialogues: list[tuple[int, str]] = []
    dialogue_speakers: dict[int, list[str]] = {}
    dialogue_tones: dict[int, str] = {}
    dialogue_identity_clues: dict[int, str | None] = {}
    used_indices: set[int] = set()
    next_index = 1
    for dialogue in merged.dialogues:
        if not dialogue.content or not dialogue.content.strip():
            continue
        index = _locate_dialogue_index(dialogue.content, chunk_text, used_indices, next_index)
        used_indices.add(index)
        if index > next_index:
            next_index = index + 1
        dialogues.append((index, dialogue.content))
        if dialogue.speaker:
            dialogue_speakers[index] = dialogue.speaker
        if dialogue.tone:
            dialogue_tones[index] = dialogue.tone
        if dialogue.identity_clue:
            dialogue_identity_clues[index] = dialogue.identity_clue

    dialogue_snapshots, dialogue_lengths = build_dialogue_snapshots(
        dialogues,
        dialogue_speakers=dialogue_speakers,
        dialogue_tones=dialogue_tones,
        dialogue_identity_clues=dialogue_identity_clues,
    )
    has_dialogues = bool(dialogue_snapshots)

    relations: list[RelationChangeSnapshot] | None = None
    if merged.relations:
        relations = [
            RelationChangeSnapshot(
                from_name=relation.from_name,
                to_name=relation.to_name,
                type=relation.type,
                change=relation.change,
                evidence=relation.evidence,
                confidence=1.0,
            )
            for relation in merged.relations
        ]

    return AnnotationChunkResult(
        annotation=annotation,
        foreshadowing=foreshadowing,
        dialogue_speakers=dialogue_speakers if has_dialogues else None,
        dialogues=dialogues if has_dialogues else None,
        dialogue_tones=dialogue_tones if has_dialogues else None,
        dialogue_identity_clues=dialogue_identity_clues if has_dialogues else None,
        dialogue_lengths=dialogue_lengths if has_dialogues else None,
        relations=relations,
    )


class AnnotationAgentRunError(RuntimeError):
    """标注 agent 运行失败"""


async def run_annotation_agent(
    *,
    chunk_text: str,
    chunk_id: int,
    total_chunks: int,
    novel_id: str,
    novel_title: str | None = None,
    chapter_id: int | None = None,
    chapter_context: str | None = None,
    global_context: str | None = None,
    prev_summary: str | None = None,
    memory: IdentityMemory | None = None,
    evidence_service: NarrativeEvidenceService | None = None,
    llm: Any | None = None,
    run_id: str | None = None,
    main_characters: str | None = None,
    session: Any | None = None,
) -> tuple[AnnotationChunkResult, IdentityMemory]:
    """
    运行标注 agent（单子块）

    超长章节场景：同一章节的每个子 chunk 都通过本入口启动独立子代理会话，
    共享同一 identity memory，state 中注入 chapter_context 保证章节叙事连贯
    """
    start_time = time.time()
    memory = memory or IdentityMemory()

    if llm is None:
        from src.agents.llm import build_chat_model

        llm = build_chat_model("annotation")

    tools = build_annotation_tools(
        evidence_service,
        memory,
        run_id=run_id,
        chunk_id=chunk_id,
    )
    graph = build_annotation_graph(llm, tools)

    position_pct = (chunk_id / total_chunks * 100) if total_chunks > 0 else 0.0

    system_prompt = build_system_prompt(
        novel_title=novel_title,
        main_characters=main_characters,
        position_pct=position_pct,
        chapter_id=chapter_id,
        memory=memory,
        prev_summary=prev_summary,
        global_context=global_context,
    )

    user_content_parts = [f"<Current_Chunk>\n{chunk_text}\n</Current_Chunk>"]
    if chapter_context:
        user_content_parts.append(
            f"<同章节其余内容>\n{chapter_context}\n</同章节其余内容>\n"
            "（同章节其余内容仅用于保持章节叙事连贯，标注对象仍以 Current_Chunk 为主）"
        )
    user_content = "\n\n".join(user_content_parts)

    from langchain_core.messages import HumanMessage, SystemMessage

    initial_state = {
        "messages": [SystemMessage(content=system_prompt), HumanMessage(content=user_content)],
        "attempts": 0,
        "output": None,
        "error": None,
    }

    try:
        result_state = await graph.ainvoke(initial_state)
    except Exception as exc:  # noqa: BLE001
        logger.error("annotation agent graph failed: chunk_id={} error={}", chunk_id, exc)
        raise AnnotationAgentRunError(f"标注 agent 运行失败: {exc}") from exc

    if result_state.get("error"):
        error = str(result_state["error"])
        logger.error("annotation agent finalize error: chunk_id={} error={}", chunk_id, error)
        raise AnnotationAgentRunError(error)

    raw_output = result_state.get("output")
    if raw_output is None:
        raise AnnotationAgentRunError("标注 agent 未产出结果")

    merged = MergedChunkAnnotation.model_validate(raw_output)
    # 应用身份决策到记忆
    memory.apply_decisions([decision.model_dump() for decision in merged.identity_decisions])

    result = convert_merged_output(merged, chunk_text)

    elapsed = time.time() - start_time
    _record_annotation_interaction(
        session=session,
        run_id=run_id,
        chunk_id=chunk_id,
        llm=llm,
        initial_messages=[SystemMessage(content=system_prompt), HumanMessage(content=user_content)],
        raw_output=raw_output,
        elapsed=elapsed,
    )
    logger.info(
        "annotation agent complete: chunk_id={} characters={} foreshadowing={} dialogues={} "
        "relations={} identity_decisions={} elapsed={:.2f}s",
        chunk_id,
        len(merged.characters),
        merged.foreshadowing is not None,
        len(merged.dialogues),
        len(merged.relations),
        len(merged.identity_decisions),
        elapsed,
    )
    return result, memory


def _record_annotation_interaction(
    *,
    session: Any,
    run_id: str | None,
    chunk_id: int,
    llm: Any,
    initial_messages: list,
    raw_output: dict,
    elapsed: float,
) -> None:
    """记录标注 agent 的模型交互（供交互回放与审计）"""
    if session is None or not run_id:
        return
    try:
        from src.models.interactions import record_model_interaction

        messages = [{"role": msg.type, "content": msg.content} for msg in initial_messages]
        response_text = str(raw_output)
        raw_base_url = getattr(llm, "base_url", "") or getattr(llm, "openai_api_base", "") or ""
        base_url = str(raw_base_url)
        provider = "cloud" if base_url and "localhost" not in base_url and "127.0.0.1" not in base_url else "local"
        record_model_interaction(
            run_id=run_id,
            chunk_id=chunk_id,
            interaction_type="annotate",
            phase="agent",
            attempt_number=1,
            messages=messages,
            response_text=response_text,
            thinking_content=None,
            duration_ms=int(elapsed * 1000),
            model_name=getattr(llm, "model_name", None),
            model_provider=provider,
            session=session,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to record annotation agent interaction: {}", exc)
