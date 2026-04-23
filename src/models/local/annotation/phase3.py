"""
创建时间: 2026-03-21
创建者: TraeAI
任务: refactor-phase3-to-annotation-layer
说明: Phase3 对话归属判断逻辑，从 workflows/annotate_helpers/sentence.py 迁移

修改历史:
- 2026-03-21: 从 sentence.py 迁移 attribute_dialogues_with_llm 和相关函数

修改时间: 2026-03-21
修改者: TraeAI
任务: migrate-litellm-to-openai-sdk
修改内容: 移除 litellm_utils 导入，直接使用配置中的模型名称

修改时间: 2026-03-22
修改者: TraeAI
任务: code-quality-review
修改内容: 对话归属失败时抛出 DialogueAttributionError 而非静默返回空字典

修改时间: 2026-03-23
修改者: TraeAI
任务: refactor-dialogue-attribution-pipeline
修改内容: 重构对话提取函数，返回 QuoteCandidate 列表，提取上下文

修改时间: 2026-03-27
修改者: TraeAI
任务: 创建统一的模型交互记录接口
修改内容: 使用 record_model_interaction 替代本地 _save_interaction 函数

修改时间: 2026-03-28
修改者: TraeAI
任务: consolidate-codebase-architecture
修改内容: 从 constants 导入 PHASE3_MAX_RETRIES，移除本地重复定义

修改时间: 2026-04-17
修改者: TraeAI
任务: fix-phase3-alias-priority-conflict
修改内容: Phase3 evidence sections 改由 renderer helper 产出，复用 Phase1 别名优先级规则

修改时间: 2026-04-22
修改者: Codex
任务: unify-estimated-token-accounting
修改内容: Phase3 在持久化 model_interactions 后同步写入统一估算 token_usage

修改时间: 2026-04-22
修改者: Codex
任务: fix-token-coverage-fallback-bucket
修改内容: 即使重试器把 Phase3 切到 annotation_fallback 执行，也仍按 annotation 主业务桶记账

修改时间: 2026-04-23
任务: annotation-projector-runtime-landing
修改内容: 单批模型调用改用 thin phase runtime，对话校验和长度派生迁入 dialogue projector。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

from src.config import settings
from src.models.local.annotation.context import DialogueAttributionError
from src.models.local.annotation.evidence_renderer import render_dialogue_attribution_evidence_sections
from src.models.local.annotation.projectors.dialogue import (
    DialogueLengthResult,
    normalize_dialogue_records,
    project_dialogue_lengths,
)
from src.models.local.annotation.runtime import AnnotationPhaseCallSpec, execute_phase_call
from src.models.local.retry_handler import AnnotationRetryHandler, RetryConfig
from src.models.local.schema import DialogueAttributionResult, DialogueRecord, DialogueRecordSchema, QuoteCandidate

if TYPE_CHECKING:
    from src.models.annotation import AnnotationClient
    from src.rag.evidence_types import EvidenceBundle


def extract_dialogues_from_text(text: str, context_chars: int = 50) -> list[QuoteCandidate]:
    """
    从文本中提取所有引号候选及其上下文

    创建时间: 2026-03-20
    创建者: TraeAI
    任务: analyze-dialogue-length-zero
    说明: 使用正则提取所有双引号包裹的对话内容

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: fix-dialogue-extraction-quotes
    修改内容: 支持中文双引号、英文双引号、中文方引号等多种引号格式，避免重复匹配

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: fix-dialogue-extraction-chinese-quotes
    修改内容: 修复中文双引号正则，添加「」和『』的匹配

    修改时间: 2026-03-23
    创建者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    修改内容: 返回 QuoteCandidate 列表，提取 ctx_before 上下文

    修改时间: 2026-03-31
    修改者: TraeAI
    任务: cleanup-phase3-ctx-context
    修改内容: 移除 ctx_before 和 ctx_after，只保留 content

    Args:
        text: 原文文本
        context_chars: 上下文字符数（已废弃，LLM 有完整 chunk_text）

    Returns:
        QuoteCandidate 列表，包含 index, content
    """
    candidates: list[QuoteCandidate] = []
    seen_positions = set()
    patterns = [
        r'"([^"]*)"',  # 英文双引号 U+0022
        r"\u201c([^\u201d]*)\u201d",  # 中文双引号（左" U+201C 右" U+201D）
        r"\u2018([^\u2019]*)\u2019",  # 中文单引号（左' U+2018 右' U+2019）
        r"「([^」]*)」",  # 中文方引号「」
        r"『([^』]*)』",  # 中文书名号『』
    ]
    all_matches = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            if match.start() in seen_positions:
                continue
            seen_positions.add(match.start())
            all_matches.append(match)
    all_matches.sort(key=lambda m: m.start())
    for idx, match in enumerate(all_matches, 1):
        content = match.group(1).strip()
        if content:
            candidates.append(
                QuoteCandidate(
                    index=idx,
                    content=content,
                )
            )
    return candidates


def _collect_priority_candidate_names(
    evidence_bundle: EvidenceBundle | None,
    batch_candidates: list[QuoteCandidate],
) -> list[str] | None:
    if evidence_bundle is None or not evidence_bundle.requested_names:
        return None

    batch_text = "\n".join(candidate.content for candidate in batch_candidates if candidate.content)
    priority_names = [name for name in evidence_bundle.requested_names if name and name in batch_text]
    return priority_names or None


async def attribute_dialogues_with_llm(
    client: AnnotationClient,
    chunk_text: str,
    candidates: list[QuoteCandidate],
    known_characters: list[str] | None = None,
    alias_map: dict[str, str] | None = None,
    evidence_bundle: EvidenceBundle | None = None,
    chunk_id: int | None = None,
    run_id: str | None = None,
    active_entities: str | None = None,
    fallback_client: AnnotationClient | None = None,
) -> list[DialogueRecord]:
    """
    使用 LLM 判断对话候选是否是对话，并识别说话者和语气

    创建时间: 2026-03-20
    创建者: TraeAI
    任务: analyze-dialogue-length-zero
    说明: 调用 LLM 根据上下文判断每段对话的说话者

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构 AnnotationClient 使用 async
    修改内容: 改为 async def

    修改时间: 2026-04-17
    修改者: TraeAI
    任务: fix-phase3-active-entities-fallback
    修改内容: 新增 active_entities 参数，优先使用上游已解析好的活跃实体上下文

    修改时间: 2026-04-20
    修改者: Codex
    任务: strict-phase34-fallback
    修改内容: 接入 fallback_client，确保 Phase3 与 Phase1/2 一致走主客户端重试后再兜底
    """
    if not candidates:
        return []

    config = client._config
    if not config.model:
        raise ValueError("model is required")

    batch_size = settings.thinking.phase3_candidates_per_batch

    async def _execute_single_batch(
        current_client: AnnotationClient,
        batch_candidates: list[QuoteCandidate],
        batch_idx: int,
        total_batches: int,
    ) -> list[DialogueRecordSchema]:
        dialogue_list = "\n".join([f'{c.index}. content: "{c.content}"' for c in batch_candidates])
        known_chars = "、".join(known_characters) if known_characters else "无"
        # 中文注释：Phase3 的共享 evidence 需要按当前 batch 重新裁剪，
        # 否则整段 chunk 的前几个候选会长期挤占 prompt，后续 batch 看不到真正相关的别名候选。
        evidence_sections = render_dialogue_attribution_evidence_sections(
            evidence_bundle,
            alias_map=alias_map,
            active_entities=active_entities,
            priority_candidate_names=_collect_priority_candidate_names(evidence_bundle, batch_candidates),
        )

        prompts = settings.prompts
        system_prompt = prompts.phase3.system
        user_template = prompts.phase3.user_template
        user_prompt = user_template.format(
            chunk_text=chunk_text,
            dialogue_list=dialogue_list,
            known_characters=known_chars,
        )
        if evidence_sections:
            # 中文注释：Phase3 只消费上游已经准备好的共享 evidence blocks，
            # 不在对话归属阶段重新发起取证，避免 Phase3 再次长成独立上下文体系。
            user_prompt += "\n\n" + "\n\n".join(evidence_sections)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        call_result = await execute_phase_call(
            current_client,
            AnnotationPhaseCallSpec(
                phase="phase3",
                interaction_type="dialogue_attribution",
                call_type="phase3",
                messages=messages,
                response_model=DialogueAttributionResult,
                chunk_id=chunk_id,
                run_id=run_id,
                attempt_number=batch_idx + 1,
            ),
        )
        parsed = call_result.parsed

        logger.info(
            f"dialogue_attribution batch: "
            f"batch={batch_idx + 1}/{total_batches} "
            f"candidates={len(batch_candidates)} "
            f"result_count={len(parsed.dialogues)}"
        )

        return parsed.dialogues

    async def _execute_all_batches(
        current_client: AnnotationClient,
    ) -> list[DialogueRecord]:
        all_results: list[DialogueRecord] = []
        total_batches = (len(candidates) + batch_size - 1) // batch_size

        for i in range(0, len(candidates), batch_size):
            batch_candidates = candidates[i : i + batch_size]
            batch_idx = i // batch_size

            phase3_max_retries = settings.runtime.annotation.phase3_max_retries
            retry_config = RetryConfig(
                max_retries=phase3_max_retries,
                operation_name=f"phase3_dialogue_attribution_batch_{batch_idx}",
                chunk_id=chunk_id,
            )

            retry_handler: AnnotationRetryHandler[list[DialogueRecordSchema]] = AnnotationRetryHandler(
                config=retry_config,
                primary_client=current_client,
                fallback_client=fallback_client,
                exception_type=DialogueAttributionError,
            )

            async def batch_operation(
                working_client: AnnotationClient,
                bc: list[QuoteCandidate] = batch_candidates,
                bi: int = batch_idx,
                tb: int = total_batches,
            ) -> list[DialogueRecordSchema]:
                # 中文注释：重试器可能把执行客户端切到 fallback_client，这里必须消费传入的 working_client，
                # 不能继续闭包捕获 current_client，否则 fallback 分支永远不会真正生效。
                return await _execute_single_batch(working_client, bc, bi, tb)

            batch_results = await retry_handler.execute(batch_operation)

            if batch_results:
                batch_records = _post_process_validation(
                    batch_results, batch_candidates, known_characters, alias_map, chunk_id
                )
                all_results.extend(batch_records)

        return all_results

    try:
        result = await _execute_all_batches(client)
        return result
    except Exception as e:
        logger.warning(f"Failed to attribute dialogues with LLM: {e}")
        raise DialogueAttributionError(f"对话归属判断失败: {e}") from e


def _post_process_validation(
    records: list[DialogueRecordSchema],
    candidates: list[QuoteCandidate],
    known_characters: list[str] | None,
    alias_map: dict[str, str] | None,
    chunk_id: int | None,
) -> list[DialogueRecord]:
    """
    后处理验证：验证 index 范围、别名归一化。

    设计决策（2026-04-10）：
    ─────────────────────────────
    此函数只做两件事：1) 校验 index 有效性；2) 别名归一化。
    不对 speaker 做任何丢弃或修正。原因：

    1. 漏标注(null) > 错标注(A→B)：
       - 错标注是脏数据，静默污染下游指标（关系图谱、对话长度、情绪曲线）
       - 漏标注是缺数据，有明确信号，消歧系统可以补全
       - 因此"宁可漏，不可错"

    2. identity_clue 不能用于修正 speaker：
       - clue 和 speaker 是同一个 LLM 从同一段上下文推断的
       - 能识别 speaker 时 clue 自然包含该信息，识别不出时 clue 也帮不上忙
       - 用正则从自然语言 clue 中反推名字不可靠（格式不可控、覆盖面窄）
       - 已删除 _extract_speaker_from_clue 函数

    3. Prompt 规则5/6 的分工：
       - 规则5：LLM 不确定 → speaker=null（漏标不错标）
       - 规则6：LLM 确定、名字不在已知列表 → 直接输出（不浪费信息）
       - 后处理不再因"不在已知列表"而丢弃/修正 speaker

    修改历史:
    - 2026-03-23: 添加 candidates 参数验证 index 范围
    - 2026-03-31: 增加 identity_clue 反推逻辑（后证明不可靠，已删除）
    - 2026-04-08: speaker 改为 list[str]，适配多人说话场景
    - 2026-04-10: 删除 _extract_speaker_from_clue 调用和所有 speaker
      修正/丢弃逻辑，只保留别名归一化和日志记录

    修改时间: 2026-04-23
    任务: annotation-projector-runtime-landing
    修改内容: 保留兼容入口，实际投影逻辑委托 dialogue projector。
    """
    return normalize_dialogue_records(records, candidates, known_characters, alias_map, chunk_id)


async def compute_dialogue_lengths_with_llm(
    client: AnnotationClient,
    text: str,
    alias_map: dict[str, str] | None = None,
    evidence_bundle: EvidenceBundle | None = None,
    chunk_id: int | None = None,
    run_id: str | None = None,
    known_characters: list[str] | None = None,
    return_tones: bool = False,
    return_identity_clues: bool = False,
    active_entities: str | None = None,
    fallback_client: AnnotationClient | None = None,
) -> DialogueLengthResult:
    """
    计算每个说话者的对话长度（使用 LLM 判断说话者）

    创建时间: 2026-03-20
    创建者: TraeAI
    任务: analyze-dialogue-length-zero
    说明: 调用 LLM 根据上下文判断每段对话的说话者

    修改时间: 2026-04-09
    修改者: TraeAI
    任务: 重构 AnnotationClient 使用 async
    修改内容: 改为 async def

    修改时间: 2026-04-10
    修改者: GLM-5
    任务: fix/disambig-retriever-integration
    修改内容: 返回 DialogueLengthResult 替代多类型 tuple，
              修复 speakers_str 二次归一化无效问题

    修改时间: 2026-04-20
    修改者: Codex
    任务: strict-phase34-fallback
    修改内容: 接入 fallback_client，确保 Phase3 的批次归属也支持云端兜底

    修改时间: 2026-04-23
    任务: annotation-projector-runtime-landing
    修改内容: 对话长度、归属、tone 与 identity clue 派生改由 dialogue projector 完成。
    """
    logger.info(f"compute_dialogue_lengths_with_llm: chunk_id={chunk_id} text_len={len(text) if text else 0}")

    if not text:
        logger.info("compute_dialogue_lengths_with_llm: early return - text_empty=True")
        return DialogueLengthResult()

    candidates = extract_dialogues_from_text(text)
    logger.info(f"compute_dialogue_lengths_with_llm: extracted {len(candidates)} candidates")
    if not candidates:
        return DialogueLengthResult()

    records = await attribute_dialogues_with_llm(
        client,
        text,
        candidates,
        known_characters=known_characters,
        alias_map=alias_map,
        evidence_bundle=evidence_bundle,
        chunk_id=chunk_id,
        run_id=run_id,
        active_entities=active_entities,
        fallback_client=fallback_client,
    )
    logger.info(f"compute_dialogue_lengths_with_llm: got {len(records)} records")

    result = project_dialogue_lengths(
        records,
        candidates,
        return_tones=return_tones,
        return_identity_clues=return_identity_clues,
    )
    logger.info(f"compute_dialogue_lengths_with_llm: result={result.speaker_lengths}")
    return result
