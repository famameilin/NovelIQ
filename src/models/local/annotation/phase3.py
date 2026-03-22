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
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from loguru import logger

from src.config import settings
from src.models.local.annotation.context import DialogueAttributionError

if TYPE_CHECKING:
    from src.models.local.annotation_client import AnnotationClient
    from src.models.local.unified_client import UnifiedModelClient


def _get_annotation_client(client: UnifiedModelClient | AnnotationClient) -> AnnotationClient:
    """从 UnifiedModelClient 或直接返回 AnnotationClient"""
    if hasattr(client, "_annotation_client"):
        return client._annotation_client
    return client


def _get_unified_client(client: UnifiedModelClient | AnnotationClient) -> UnifiedModelClient | AnnotationClient:
    """如果输入是 AnnotationClient，直接返回；如果是 UnifiedModelClient 也返回自身"""
    return client


def extract_dialogues_from_text(text: str) -> list[tuple[int, str]]:
    """
    从文本中提取所有对话

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

    Args:
        text: 原文文本

    Returns:
        [(index, content), ...] 对话序号（1开始）和内容
    """
    dialogues = []
    seen_positions = set()
    patterns = [
        r'"([^"]*)"',  # 英文双引号 U+0022
        r"[\u201c\u201e]([^\u201c\u201e]*)[\u201c\u201e]",  # 中文双引号 U+201C/U+201D
        r"['\u2018\u2019]([^'\u2018\u2019]*)['\u2018\u2019]",  # 中文单引号 U+2018/U+2019
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
            dialogues.append((idx, content))
    return dialogues


def _save_interaction(
    client: UnifiedModelClient | AnnotationClient,
    run_id: str | None,
    chunk_id: int | None,
    phase: str,
    attempt_number: int,
    messages: list[dict],
    content_clean: str,
    thinking_content: str | None,
    duration_ms: int,
    is_cloud: bool,
) -> None:
    """
    保存模型交互记录

    创建时间: 2026-03-21
    创建者: TraeAI
    任务: refactor-phase3-to-annotation-layer
    说明: 与 phase1/phase2 保持一致的交互记录保存逻辑
    """
    if not run_id:
        return

    try:
        from src.storage.repositories.model_interaction_repository import ModelInteractionRepository

        prompt_text = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

        annotation_client = _get_annotation_client(client)
        if hasattr(annotation_client, "_session") and annotation_client._session is not None:
            repo = ModelInteractionRepository(annotation_client._session)
            repo.save_interaction(
                run_id=run_id,
                chunk_id=chunk_id,
                interaction_type="dialogue_attribution",
                phase=phase,
                attempt_number=attempt_number,
                model_name=annotation_client._config.model if hasattr(annotation_client._config, "model") else None,
                model_provider="cloud" if is_cloud else "local",
                prompt=prompt_text,
                response=content_clean,
                thinking=thinking_content,
                duration_ms=duration_ms,
            )
    except Exception as e:
        logger.warning(f"Failed to save phase3 interaction: {e}")


def attribute_dialogues_with_llm(
    client: UnifiedModelClient | AnnotationClient,
    chunk_text: str,
    dialogues: list[tuple[int, str]],
    known_characters: list[str] | None = None,
    chunk_id: int | None = None,
    run_id: str | None = None,
) -> dict[int, str]:
    """
    使用 LLM 判断对话说话者

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

    Args:
        client: 统一模型客户端
        chunk_text: chunk 原文
        dialogues: 对话列表 [(index, content), ...]
        known_characters: 已知人物列表，None 时 LLM 自由判断
        chunk_id: chunk ID（用于交互记录）
        run_id: 运行 ID（用于交互记录）

    Returns:
        {index: speaker} 对话序号到说话者的映射
    """
    if not dialogues:
        return {}

    dialogue_list = "\n".join([f'{i}. "{content}"' for i, content in dialogues])
    known_chars = "、".join(known_characters) if known_characters else "无"

    prompts = settings.prompts
    system_prompt = prompts.dialogue_attribution_system
    user_template = prompts.dialogue_attribution_user_template
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
    try:
        from src.models.local.schema import DialogueAttributionResult

        annotation_client = _get_annotation_client(client)
        config = annotation_client._config

        if not config.model:
            raise ValueError("model is required")

        is_cloud = annotation_client._is_cloud_api()
        enable_thinking = config.thinking_enabled

        parsed, response = annotation_client._call_annotation_api(
            messages=messages,
            enable_thinking=enable_thinking,
            chunk_id=chunk_id,
            response_model=DialogueAttributionResult,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        content_clean = str(parsed.model_dump())
        _save_interaction(
            client=_get_unified_client(client),
            run_id=run_id,
            chunk_id=chunk_id,
            phase="phase3",
            attempt_number=1,
            messages=messages,
            content_clean=content_clean,
            thinking_content=None,
            duration_ms=duration_ms,
            is_cloud=is_cloud,
        )

        logger.info(
            f"dialogue_attribution: chunk_text_len={len(chunk_text)} dialogues={len(dialogues)} result_count={len(parsed.dialogues)}"
        )

        return {d.index: d.speaker for d in parsed.dialogues}
    except Exception as e:
        logger.warning(f"Failed to attribute dialogues with LLM: {e}")
        raise DialogueAttributionError(f"对话归属判断失败: {e}") from e


def compute_dialogue_lengths_with_llm(
    client: UnifiedModelClient | AnnotationClient,
    text: str,
    speakers: list[str],
    alias_map: dict[str, str] | None = None,
    chunk_id: int | None = None,
    run_id: str | None = None,
) -> list[int]:
    """
    计算每个说话者的对话长度（使用 LLM 判断）

    创建时间: 2026-03-20
    创建者: TraeAI
    任务: analyze-dialogue-length-zero
    说明: 改进版本，用正则提取对话内容，用 LLM 判断说话者

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: refactor-phase3-to-annotation-layer
    修改内容: 迁移到 models/local/annotation/phase3.py，添加 chunk_id 和 run_id 参数

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: fix-dialogue-extraction-quotes
    修改内容: 添加调试日志

    修改时间: 2026-03-22
    修改者: TraeAI
    任务: fix-phase3-speaker-alias-mapping
    修改内容: 添加 alias_map 参数，LLM 自由判断说话者并通过 alias_map 映射到规范名

    Args:
        client: 统一模型客户端
        text: chunk 原文
        speakers: 说话者列表（用于返回结果顺序）
        alias_map: 别名到规范名的映射，None 时不进行映射
        chunk_id: chunk ID（用于交互记录）
        run_id: 运行 ID（用于交互记录）

    Returns:
        每个说话者的对话长度列表（与 speakers 顺序对应）
    """
    logger.info(
        f"compute_dialogue_lengths_with_llm: chunk_id={chunk_id} text_len={len(text) if text else 0} speakers={speakers}"
    )

    if not text or not speakers:
        logger.info(
            f"compute_dialogue_lengths_with_llm: early return - text_empty={not text} speakers_empty={not speakers}"
        )
        return [0] * len(speakers)

    dialogues = extract_dialogues_from_text(text)
    logger.info(f"compute_dialogue_lengths_with_llm: extracted {len(dialogues)} dialogues")
    if not dialogues:
        return [0] * len(speakers)

    attribution = attribute_dialogues_with_llm(client, text, dialogues, known_characters=None, chunk_id=chunk_id, run_id=run_id)
    logger.info(f"compute_dialogue_lengths_with_llm: attribution={attribution}")

    speaker_lengths: dict[str, int] = {}
    for idx, content in dialogues:
        raw_speaker = attribution.get(idx, "")
        if raw_speaker and raw_speaker != "未知":
            canonical = alias_map.get(raw_speaker, raw_speaker) if alias_map else raw_speaker
            speaker_lengths[canonical] = speaker_lengths.get(canonical, 0) + len(content)

    result = [speaker_lengths.get(s, 0) for s in speakers]
    logger.info(f"compute_dialogue_lengths_with_llm: result={result}")
    return result
