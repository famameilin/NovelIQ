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
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from loguru import logger

from src.config import settings
from src.config.constants import PHASE3_MAX_RETRIES
from src.models.interactions import record_model_interaction
from src.models.local.annotation.context import DialogueAttributionError
from src.models.local.retry_handler import AnnotationRetryHandler, RetryConfig
from src.models.local.schema import DialogueAttributionResult, DialogueRecord, QuoteCandidate

if TYPE_CHECKING:
    from src.models.annotation import AnnotationClient


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
    修改者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    修改内容: 返回 QuoteCandidate 列表，提取 ctx_before 和 ctx_after 上下文

    Args:
        text: 原文文本
        context_chars: 上下文字符数，默认 50

    Returns:
        QuoteCandidate 列表，包含 index, ctx_before, content, ctx_after
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
            start = match.start()
            end = match.end()
            ctx_before = text[max(0, start - context_chars) : start].strip()
            ctx_after = text[end : min(len(text), end + context_chars)].strip()
            candidates.append(
                QuoteCandidate(
                    index=idx,
                    ctx_before=ctx_before,
                    content=content,
                    ctx_after=ctx_after,
                )
            )
    return candidates


def attribute_dialogues_with_llm(
    client: AnnotationClient,
    chunk_text: str,
    candidates: list[QuoteCandidate],
    known_characters: list[str] | None = None,
    alias_map: dict[str, str] | None = None,
    chunk_id: int | None = None,
    run_id: str | None = None,
) -> list[DialogueRecord]:
    """
    使用 LLM 判断对话候选是否是对话，并识别说话者和语气

    创建时间: 2026-03-20
    创建者: TraeAI
    任务: analyze-dialogue-length-zero
    说明: 调用 LLM 根据上下文判断每段对话的说话者

    修改时间: 2026-03-20
    修改者: TraeAI
    任务: fix-dialogue-attribution-parsing
    修改内容: 使用正确的 API 调用方式，直接解析 LLM 返回的 JSON 为 DialogueAttributionResult

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: refactor-phase3-to-annotation-layer
    修改内容: 迁移到 models/local/annotation/phase3.py，添加 chunk_id 和 run_id 参数支持交互记录保存

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: fix-phase3-speaker-alias-mapping
    修改内容: known_characters 改为可选参数，支持 None 让 LLM 自由判断说话者

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    修改内容:
    - 接收 QuoteCandidate 列表替代 tuple 列表
    - 返回 DialogueRecord 列表替代 dict
    - 添加失败重试机制
    - 添加后处理验证

    Args:
        client: 统一模型客户端
        chunk_text: chunk 原文
        candidates: 引号候选列表 [QuoteCandidate, ...]
        known_characters: 已知人物列表，None 时 LLM 自由判断
        alias_map: 别名映射表，用于说话者归一化
        chunk_id: chunk ID（用于交互记录）
        run_id: 运行 ID（用于交互记录）

    Returns:
        DialogueRecord 列表
    """
    if not candidates:
        return []

    config = client._config
    if not config.model:
        raise ValueError("model is required")

    is_cloud = client._is_cloud_api()
    enable_thinking = config.thinking_enabled

    def _execute_call(
        current_client: AnnotationClient,
        retry_messages: list[dict] | None = None,
    ) -> list[DialogueRecord]:
        dialogue_list = "\n".join(
            [
                f'{c.index}. ctx_before: "{c.ctx_before}"\n   content: "{c.content}"\n   ctx_after: "{c.ctx_after}"'
                for c in candidates
            ]
        )
        known_chars = "、".join(known_characters) if known_characters else "无"

        prompts = settings.prompts
        system_prompt = prompts.phase3.system
        user_template = prompts.phase3.user_template
        user_prompt = user_template.format(
            chunk_text=chunk_text,
            dialogue_list=dialogue_list,
            known_characters=known_chars,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        start_time = time.time()
        parsed, response = current_client._call_annotation_api(
            messages=messages,
            enable_thinking=enable_thinking,
            chunk_id=chunk_id,
            response_model=DialogueAttributionResult,
        )

        duration_ms = int((time.time() - start_time) * 1000)
        content_clean = str(parsed.model_dump())

        record_model_interaction(
            run_id=run_id,
            chunk_id=chunk_id,
            interaction_type="dialogue_attribution",
            phase="phase3",
            attempt_number=1,
            messages=messages,
            response_text=content_clean,
            thinking_content=None,
            duration_ms=duration_ms,
            model_name=current_client._config.model,
            model_provider="cloud" if is_cloud else "local",
            session=current_client._session,
        )

        logger.info(
            f"dialogue_attribution: chunk_text_len={len(chunk_text)} candidates={len(candidates)} result_count={len(parsed.dialogues)}"
        )

        return parsed.dialogues

    retry_config = RetryConfig(
        max_retries=PHASE3_MAX_RETRIES,
        operation_name="phase3_dialogue_attribution",
        chunk_id=chunk_id,
    )

    retry_handler: AnnotationRetryHandler[list[DialogueRecord]] = AnnotationRetryHandler(
        config=retry_config,
        local_client=client,
        cloud_client=None,
        exception_type=DialogueAttributionError,
    )

    try:
        result = retry_handler.execute(_execute_call)
        if result is None:
            return []
        return _post_process_validation(result, candidates, known_characters, alias_map, chunk_id)
    except Exception as e:
        logger.warning(f"Failed to attribute dialogues with LLM: {e}")
        raise DialogueAttributionError(f"对话归属判断失败: {e}") from e


def _post_process_validation(
    records: list[DialogueRecord],
    candidates: list[QuoteCandidate],
    known_characters: list[str] | None,
    alias_map: dict[str, str] | None,
    chunk_id: int | None,
) -> list[DialogueRecord]:
    """
    后处理验证：验证 index 范围和说话者有效性

    创建时间: 2026-03-23
    创建者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    说明: 验证 LLM 返回的 speaker 是否在已知人物列表中，如果不在则记录警告日志

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: fix-phase3-validation
    修改内容: 添加 candidates 参数验证 index 范围，跳过未知说话者的记录
    """
    valid_records = []
    candidate_indices = {c.index for c in candidates}
    known_set = None
    if known_characters:
        known_set = {alias_map.get(name, name) if alias_map else name for name in known_characters}

    for record in records:
        if record.index not in candidate_indices:
            logger.warning(
                f"phase3_validation: invalid index {record.index}, "
                f"not in candidates range, skipping, chunk_id={chunk_id}"
            )
            continue

        canonical_speaker = record.speaker
        if canonical_speaker and alias_map:
            canonical_speaker = alias_map.get(canonical_speaker, canonical_speaker)

        if known_set and canonical_speaker and canonical_speaker not in known_set:
            logger.warning(
                f"phase3_validation: unknown speaker '{record.speaker}', "
                f"skipping record, chunk_id={chunk_id}, index={record.index}"
            )
            continue

        if canonical_speaker != record.speaker:
            valid_records.append(record.model_copy(update={"speaker": canonical_speaker}))
        else:
            valid_records.append(record)

    return valid_records


def compute_dialogue_lengths_with_llm(
    client: AnnotationClient,
    text: str,
    alias_map: dict[str, str] | None = None,
    chunk_id: int | None = None,
    run_id: str | None = None,
    known_characters: list[str] | None = None,
    return_tones: bool = False,
    return_evidences: bool = False,
    return_identity_clues: bool = False,
) -> (
    tuple[dict[str, int], dict[int, str], list[tuple[int, str]]]
    | tuple[dict[str, int], dict[int, str], list[tuple[int, str]], dict[int, str]]
    | tuple[dict[str, int], dict[int, str], list[tuple[int, str]], dict[int, str], dict[int, str]]
    | tuple[
        dict[str, int], dict[int, str], list[tuple[int, str]], dict[int, str], dict[int, str], dict[int, str | None]
    ]
):
    """
    计算每个说话者的对话长度（使用 LLM 判断说话者）

    创建时间: 2026-03-20
    创建者: TraeAI
    任务: analyze-dialogue-length-zero
    说明: 调用 LLM 根据上下文判断每段对话的说话者

    修改时间: 2026-03-20
    修改者: TraeAI
    任务: fix-dialogue-attribution-parsing
    修改内容: 使用正确的 API 调用方式，直接解析 LLM 返回的 JSON 为 DialogueAttributionResult

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: refactor-phase3-to-annotation-layer
    修改内容: 迁移到 models/local/annotation/phase3.py，添加 chunk_id 和 run_id 参数支持交互记录保存

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: fix-phase3-speaker-alias-mapping
    修改内容: known_characters 改为可选参数，支持 None 让 LLM 自由判断说话者

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    修改内容:
    - 接收 QuoteCandidate 列表替代 tuple 列表
    - 返回 DialogueRecord 列表替代 dict
    - 添加失败重试机制
    - 添加后处理验证

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: return-attribution-for-storage
    修改内容: 返回 attribution mapping 供 storage 使用

    修改时间: 2026-03-25
    修改者: TraeAI
    任务: fix-tone-distribution-semantic-error
    修改内容: 返回 dialogue_tones 字典存储对话语气类型

    修改时间: 2026-03-28
    修改者: TraeAI
    任务: fix-unknown-speaker-context
    修改内容: 返回 dialogue_evidences 字典存储对话判断依据

    修改时间: 2026-03-29
    修改者: TraeAI
    任务: add-identity-clue-to-dialogue-record
    修改内容: 添加 return_identity_clues 参数，返回 dialogue_identity_clues 字典存储身份线索

    Returns:
        根据 return_tones/return_evidences/return_identity_clues 参数返回不同长度的元组:
        - 默认: ({说话者: 总长度}, {dialogue_idx: 说话者}, [(dialogue_idx, content), ...])
        - return_tones: (+ {dialogue_idx: tone, ...})
        - return_evidences: (+ {dialogue_idx: evidence, ...})
        - return_identity_clues: (+ {dialogue_idx: identity_clue, ...})
    """
    logger.info(f"compute_dialogue_lengths_with_llm: chunk_id={chunk_id} text_len={len(text) if text else 0}")

    if not text:
        logger.info("compute_dialogue_lengths_with_llm: early return - text_empty=True")
        if return_identity_clues:
            return ({}, {}, [], {}, {}, {})
        if return_evidences:
            return ({}, {}, [], {}, {})
        if return_tones:
            return ({}, {}, [], {})
        return ({}, {}, [])

    candidates = extract_dialogues_from_text(text)
    logger.info(f"compute_dialogue_lengths_with_llm: extracted {len(candidates)} candidates")
    if not candidates:
        if return_identity_clues:
            return ({}, {}, [], {}, {}, {})
        if return_evidences:
            return ({}, {}, [], {}, {})
        if return_tones:
            return ({}, {}, [], {})
        return ({}, {}, [])

    records = attribute_dialogues_with_llm(
        client,
        text,
        candidates,
        known_characters=known_characters,
        alias_map=alias_map,
        chunk_id=chunk_id,
        run_id=run_id,
    )
    logger.info(f"compute_dialogue_lengths_with_llm: got {len(records)} records")

    speaker_lengths: dict[str, int] = {}
    canonical_attribution: dict[int, str] = {}
    dialogues: list[tuple[int, str]] = []
    dialogue_tones: dict[int, str] = {}
    dialogue_evidences: dict[int, str] = {}
    dialogue_identity_clues: dict[int, str | None] = {}
    seen_indices: set[int] = set()

    candidate_map = {c.index: c.content for c in candidates}
    for record in records:
        if record.index in seen_indices:
            logger.warning(f"compute_dialogue_lengths_with_llm: duplicate index={record.index}, skipping duplicate")
            continue
        seen_indices.add(record.index)

        if not record.is_dialogue:
            continue

        content = candidate_map.get(record.index, "").strip()
        if not content:
            content = (record.content or "").strip()
        if not content:
            continue

        dialogues.append((record.index, content))

        if record.tone:
            dialogue_tones[record.index] = record.tone

        if record.evidence:
            dialogue_evidences[record.index] = record.evidence

        if record.identity_clue:
            dialogue_identity_clues[record.index] = record.identity_clue

        if record.speaker and record.speaker != "未知":
            canonical = alias_map.get(record.speaker, record.speaker) if alias_map else record.speaker
            speaker_lengths[canonical] = speaker_lengths.get(canonical, 0) + len(content)
            canonical_attribution[record.index] = canonical

    logger.info(f"compute_dialogue_lengths_with_llm: result={speaker_lengths}")
    if return_identity_clues:
        return (
            speaker_lengths,
            canonical_attribution,
            dialogues,
            dialogue_tones,
            dialogue_evidences,
            dialogue_identity_clues,
        )
    if return_evidences:
        return (speaker_lengths, canonical_attribution, dialogues, dialogue_tones, dialogue_evidences)
    if return_tones:
        return (speaker_lengths, canonical_attribution, dialogues, dialogue_tones)
    return (speaker_lengths, canonical_attribution, dialogues)
