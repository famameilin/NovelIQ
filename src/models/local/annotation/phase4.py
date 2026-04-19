"""
Phase4: 关系抽取（LLM调用）

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分annotation_client
说明: Phase4 关系抽取逻辑

修改时间: 2026-04-05
修改者: TraeAI
任务: refactor-phase4-relation-extraction
修改内容: 从启发式规则改为LLM调用，统一处理静态关系和关系变化
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from loguru import logger

from src.config import settings
from src.config.constants import (
    PHASE_MAX_RETRIES,
    SYMMETRIC_RELATION_TYPES,
)
from src.models.interactions import record_model_interaction
from src.models.local.annotation.evidence_renderer import render_relation_extraction_evidence_sections
from src.models.local.retry_handler import AnnotationRetryHandler, RetryConfig
from src.models.local.schema import RelationChangeSnapshot, RelationExtractionResult

if TYPE_CHECKING:
    from src.models.annotation import AnnotationClient
    from src.rag.evidence_types import EvidenceBundle


class Phase4MaxRetriesExceededError(Exception):
    """
    Phase4 重试次数耗尽异常

    创建时间: 2026-04-05
    创建者: TraeAI
    任务: refactor-phase4-relation-extraction
    说明: 当 Phase4 关系抽取重试次数耗尽时抛出此异常
    """

    pass


# 默认置信度（LLM 不输出置信度时的回退值）
_DEFAULT_RELATION_CONFIDENCE: float = 0.85


def _build_phase4_messages(
    text: str,
    known_characters: list[str] | None,
    evidence_sections: list[str] | None = None,
) -> list[dict[str, str]]:
    """
    构建 Phase4 消息

    创建时间: 2026-04-05
    创建者: TraeAI
    任务: refactor-phase4-relation-extraction

    修改时间: 2026-04-05
    修改者: TraeAI
    任务: phase4-code-review-fix
    修改内容: 添加 Prompt 空值运行时校验
    """
    from string import Template

    prompts = settings.prompts
    system_prompt = prompts.phase4.system
    user_template_str = prompts.phase4.user_template

    if not system_prompt:
        raise ValueError("Phase4 system prompt is empty, check config/prompts/phase4.txt")
    if not user_template_str:
        raise ValueError("Phase4 user template is empty, check config/prompts/phase4.txt")

    known_chars = "、".join(known_characters) if known_characters else "无"

    user_template = Template(user_template_str)
    user_prompt = user_template.substitute(
        chunk_text=text,
        known_characters=known_chars,
    )
    if evidence_sections:
        # 中文注释：Phase4 只追加 renderer 已经选好的共享 evidence blocks，
        # 不在关系抽取阶段重新定义 Level1/2/3 的文案或 section 协议。
        user_prompt += "\n\n" + "\n\n".join(evidence_sections)

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _convert_to_snapshots(
    result: RelationExtractionResult,
    source_model: str,
) -> list[RelationChangeSnapshot]:
    """
    将 LLM 输出转换为 RelationChangeSnapshot 列表

    创建时间: 2026-04-05
    创建者: TraeAI
    任务: refactor-phase4-relation-extraction

    修改时间: 2026-04-05
    修改者: TraeAI
    任务: phase4-code-review-fix
    修改内容: 移除类型验证（已由 Pydantic Literal 约束处理）
    """
    snapshots: list[RelationChangeSnapshot] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for record in result.relations:
        key = (record.from_name, record.to_name, record.type)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        snapshots.append(
            RelationChangeSnapshot(
                from_name=record.from_name,
                to_name=record.to_name,
                type=record.type,
                change=record.change,
                evidence=record.evidence,
                confidence=_DEFAULT_RELATION_CONFIDENCE,
                source_model=source_model,
                projection_status="pending",
                directionality="symmetric" if record.type in SYMMETRIC_RELATION_TYPES else "directed",
            )
        )

        # 对称关系自动生成反向边（A→B 变成 A→B + B→A）
        if record.type in SYMMETRIC_RELATION_TYPES and record.from_name != record.to_name:
            reverse_key = (record.to_name, record.from_name, record.type)
            if reverse_key not in seen_keys:
                seen_keys.add(reverse_key)
                snapshots.append(
                    RelationChangeSnapshot(
                        from_name=record.to_name,
                        to_name=record.from_name,
                        type=record.type,
                        change=record.change,
                        evidence=record.evidence,
                        confidence=_DEFAULT_RELATION_CONFIDENCE,
                        source_model=source_model,
                        projection_status="pending",
                        directionality="symmetric",
                    )
                )

    return snapshots


async def execute_phase4_call(
    client: AnnotationClient,
    text: str,
    known_characters: list[str] | None,
    messages: list[dict],
    chunk_id: int | None,
    run_id: str | None,
    attempt_number: int = 1,
) -> list[RelationChangeSnapshot]:
    """
    执行 Phase4 单次调用

    创建时间: 2026-04-05
    创建者: TraeAI
    任务: refactor-phase4-relation-extraction

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构 AnnotationClient 使用 async
    修改内容: 改为 async def
    """
    start_time = time.time()
    is_cloud = client._is_cloud_api()
    config = client._config

    enable_thinking = config.thinking_enabled

    parsed, response = await client._call_annotation_api(
        messages=messages,
        enable_thinking=enable_thinking,
        chunk_id=chunk_id,
        response_model=RelationExtractionResult,
    )

    duration_ms = int((time.time() - start_time) * 1000)
    content_clean = str(parsed.model_dump())
    thinking_content = getattr(response, "thinking_content", None)
    process_response = getattr(client, "_process_annotation_response", None)
    if callable(process_response) and hasattr(response, "choices"):
        content_clean, thinking_content, _ = process_response(response, is_cloud, chunk_id, "phase4")

    record_model_interaction(
        run_id=run_id,
        chunk_id=chunk_id,
        interaction_type="relation_extraction",
        phase="phase4",
        attempt_number=attempt_number,
        messages=messages,
        response_text=content_clean,
        thinking_content=thinking_content,
        duration_ms=duration_ms,
        model_name=config.model,
        model_provider="cloud" if is_cloud else "local",
        session=client._session,
    )

    logger.info(
        "phase4_relation_extraction: chunk_id={} text_len={} relations_count={}",
        chunk_id,
        len(text),
        len(parsed.relations),
    )

    source_model = config.model or "phase4-llm"
    return _convert_to_snapshots(parsed, source_model)


async def annotate_chunk_phase4(
    client: AnnotationClient,
    text: str,
    known_characters: list[str] | None = None,
    evidence_bundle: EvidenceBundle | None = None,
    chunk_id: int | None = None,
    run_id: str | None = None,
) -> list[RelationChangeSnapshot]:
    """
    Phase4: 关系抽取（使用 LLM）

    创建时间: 2026-03-18
    创建者: TraeAI
    任务: code-quality-refactor - Task 9 拆分annotation_client
    说明: Phase4 关系抽取逻辑

    修改时间: 2026-04-05
    修改者: TraeAI
    任务: refactor-phase4-relation-extraction
    修改内容: 从启发式规则改为LLM调用，统一处理静态关系和关系变化

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构 AnnotationClient 使用 async
    修改内容: 改为 async def
    """
    if not text:
        return []
    if not known_characters:
        return []

    logger.info(
        f"Phase4 annotate_chunk_phase4 STARTING for chunk_id={chunk_id}, "
        f"text_len={len(text)}, known_characters={known_characters}"
    )

    evidence_sections = render_relation_extraction_evidence_sections(evidence_bundle)
    messages = _build_phase4_messages(
        text,
        known_characters,
        evidence_sections=evidence_sections,
    )

    config = RetryConfig(
        max_retries=PHASE_MAX_RETRIES,
        operation_name="phase4",
        chunk_id=chunk_id,
    )
    handler = AnnotationRetryHandler[list[RelationChangeSnapshot]](
        config=config,
        local_client=client,
        cloud_client=None,
        exception_type=Phase4MaxRetriesExceededError,
    )

    async def operation(
        local_client: AnnotationClient,
        retry_messages: list[dict] | None = None,
    ) -> list[RelationChangeSnapshot]:
        current_messages = retry_messages if retry_messages else messages
        return await execute_phase4_call(
            client=local_client,
            text=text,
            known_characters=known_characters,
            messages=current_messages,
            chunk_id=chunk_id,
            run_id=run_id,
            attempt_number=handler.state.attempt,
        )

    try:
        result = await handler.execute(operation)
        return result if result else []
    except Phase4MaxRetriesExceededError:
        logger.warning("Phase4 max retries exceeded for chunk_id={}", chunk_id)
        return []
    except Exception as e:
        logger.error("Phase4 unexpected error for chunk_id={}: {}", chunk_id, e)
        raise
