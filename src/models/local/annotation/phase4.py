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

修改时间: 2026-04-22
修改者: Codex
任务: unify-estimated-token-accounting
修改内容: Phase4 在交互日志之外补记统一估算 token_usage

修改时间: 2026-04-23
任务: annotation-projector-runtime-landing
修改内容: Phase4 单次调用改用 thin phase runtime，关系快照转换迁入 relation projector。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from src.config import settings
from src.models.local.annotation.evidence_renderer import render_relation_extraction_evidence_sections
from src.models.local.annotation.projectors.relation import convert_relation_result_to_snapshots
from src.models.local.annotation.runtime import AnnotationPhaseCallSpec, execute_phase_call
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

    修改时间: 2026-04-23
    任务: annotation-projector-runtime-landing
    修改内容: 保留兼容入口，实际转换逻辑委托 relation projector。
    """
    return convert_relation_result_to_snapshots(result, source_model)


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

    修改时间: 2026-04-22
    修改者: Codex
    任务: fix-token-coverage-fallback-bucket
    修改内容: Phase4 经 annotation_fallback 执行时仍统一归入 annotation 主业务桶，
              避免 coverage 统计把 fallback 调用误报为缺口

    修改时间: 2026-04-23
    任务: annotation-projector-runtime-landing
    修改内容: 委托 execute_phase_call 统一模型调用后的记录、thinking 和 token 估算。
    """
    config = client._config

    call_result = await execute_phase_call(
        client,
        AnnotationPhaseCallSpec(
            phase="phase4",
            interaction_type="relation_extraction",
            call_type="phase4",
            messages=messages,
            response_model=RelationExtractionResult,
            chunk_id=chunk_id,
            run_id=run_id,
            attempt_number=attempt_number,
        ),
    )
    parsed = call_result.parsed

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
    fallback_client: AnnotationClient | None = None,
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

    修改时间: 2026-04-20
    修改者: Codex
    任务: strict-phase34-fallback
    修改内容: 接入 fallback_client，并在主/兜底全部失败后继续抛错，避免静默吞掉关系抽取失败
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

    phase_max_retries = settings.runtime.annotation.phase_max_retries
    config = RetryConfig(
        max_retries=phase_max_retries,
        operation_name="phase4",
        chunk_id=chunk_id,
    )
    handler = AnnotationRetryHandler[list[RelationChangeSnapshot]](
        config=config,
        primary_client=client,
        fallback_client=fallback_client,
        exception_type=Phase4MaxRetriesExceededError,
    )

    async def operation(
        primary_client: AnnotationClient,
        retry_messages: list[dict] | None = None,
    ) -> list[RelationChangeSnapshot]:
        current_messages = retry_messages if retry_messages else messages
        return await execute_phase4_call(
            client=primary_client,
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
        logger.error("Phase4 exhausted primary/fallback retries chunk_id={}", chunk_id)
        raise
    except Exception as e:
        logger.error("Phase4 unexpected error for chunk_id={}: {}", chunk_id, e)
        raise
