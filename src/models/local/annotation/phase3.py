"""
说明: Phase3 对话归属判断逻辑，从 workflows/annotate_helpers/sentence.py 迁移

修改历史:
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from loguru import logger

from src.api.models.events import StreamEvent
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


_QUOTE_PATTERNS = (
    r'"([^"]*)"',  # 英文双引号 U+0022
    r"\u201c([^\u201d]*)\u201d",  # 中文双引号（左" U+201C 右" U+201D）
    r"\u2018([^\u2019]*)\u2019",  # 中文单引号（左' U+2018 右' U+2019）
    r"「([^」]*)」",  # 中文方引号「」
    r"『([^』]*)』",  # 中文书名号『』
)
_FASTPATH_SPEECH_VERBS = (
    "冷笑道",
    "轻声道",
    "低声道",
    "说道",
    "笑道",
    "怒道",
    "喊道",
    "叫道",
    "喝道",
    "问道",
    "答道",
    "回道",
    "应道",
    "说",
    "问",
    "答",
    "喊",
    "叫",
    "喝",
    "回",
    "应",
)
_FASTPATH_COLLECTIVE_MARKERS = ("齐声", "异口同声", "众人", "大家", "两人", "三人", "几人", "人群")
_FASTPATH_PRONOUN_MARKERS = ("他", "她", "它", "他们", "她们", "它们", "自己", "对方")
_FASTPATH_DIRECTIONAL_MARKERS = ("对", "向", "跟", "朝", "冲着", "看着", "望着", "盯着", "瞧着")
_SENTENCE_BOUNDARY_CHARS = "。！？!?；;\n"


@dataclass(frozen=True)
class _QuoteMatch:
    """
    Phase3 引号匹配结果。
    """

    index: int
    content: str
    start: int
    end: int


@dataclass(frozen=True)
class _QuoteContext:
    """
    Phase3 fastpath 使用的引号上下文。
    """

    index: int
    content: str
    sentence_text: str
    prefix_text: str
    suffix_text: str


@dataclass(frozen=True)
class _FastpathEvaluation:
    """
    单个候选的 fastpath 判断结果。
    """

    record: DialogueRecordSchema | None
    hit_type: str | None = None
    reject_reason: str | None = None


def _collect_quote_matches(text: str) -> list[_QuoteMatch]:
    """
    提取按原文顺序排列的引号匹配结果。
    """
    seen_positions: set[int] = set()
    all_matches: list[re.Match[str]] = []
    for pattern in _QUOTE_PATTERNS:
        for match in re.finditer(pattern, text):
            if match.start() in seen_positions:
                continue
            seen_positions.add(match.start())
            all_matches.append(match)

    all_matches.sort(key=lambda match: match.start())
    return [
        _QuoteMatch(
            index=idx,
            content=match.group(1).strip(),
            start=match.start(),
            end=match.end(),
        )
        for idx, match in enumerate(all_matches, 1)
    ]


def _find_sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """
    计算候选所在的局部句子边界。
    """
    sentence_start = start
    while sentence_start > 0 and text[sentence_start - 1] not in _SENTENCE_BOUNDARY_CHARS:
        sentence_start -= 1

    sentence_end = end
    while sentence_end < len(text) and text[sentence_end] not in _SENTENCE_BOUNDARY_CHARS:
        sentence_end += 1
    if sentence_end < len(text):
        sentence_end += 1
    return sentence_start, sentence_end


def _build_quote_contexts(text: str) -> dict[int, _QuoteContext]:
    """
    为每个非空候选构建 fastpath 所需的上下文字段。
    """
    contexts: dict[int, _QuoteContext] = {}
    for match in _collect_quote_matches(text):
        if not match.content:
            continue
        sentence_start, sentence_end = _find_sentence_bounds(text, match.start, match.end)
        contexts[match.index] = _QuoteContext(
            index=match.index,
            content=match.content,
            sentence_text=text[sentence_start:sentence_end].strip(),
            prefix_text=text[sentence_start:match.start].strip(),
            suffix_text=text[match.end:sentence_end].strip(),
        )
    return contexts


def _build_fastpath_name_hints(
    known_characters: list[str] | None,
    alias_map: dict[str, str] | None,
) -> list[str]:
    """
    收集 fastpath 可安全使用的人名提示集。
    """
    name_hints: set[str] = set()
    for name in known_characters or []:
        normalized = name.strip()
        if len(normalized) >= 2:
            name_hints.add(normalized)
    for alias, canonical in (alias_map or {}).items():
        alias_text = alias.strip()
        canonical_text = canonical.strip()
        if len(alias_text) >= 2:
            name_hints.add(alias_text)
        if len(canonical_text) >= 2:
            name_hints.add(canonical_text)
    return sorted(name_hints, key=len, reverse=True)


def _collect_non_overlapping_name_spans(
    sentence_text: str,
    name_hints: list[str],
) -> list[tuple[int, int, str]]:
    """
    提取句子中不重叠的人名提示命中。
    """
    spans: list[tuple[int, int, str]] = []
    for name in name_hints:
        for match in re.finditer(re.escape(name), sentence_text):
            start, end = match.span()
            if any(not (end <= span_start or start >= span_end) for span_start, span_end, _ in spans):
                continue
            spans.append((start, end, name))
    spans.sort(key=lambda item: item[0])
    return spans


def _collect_unique_names(text: str, name_hints: list[str]) -> set[str]:
    """
    收集文本中的唯一人名提示命中。
    """
    return {name for _, _, name in _collect_non_overlapping_name_spans(text, name_hints)}


def _build_fastpath_speech_tag_matches(
    context: _QuoteContext,
    name_hints: list[str],
) -> tuple[re.Match[str] | None, re.Match[str] | None]:
    """
    构造 prefix / suffix speech tag 匹配结果。
    """
    names_pattern = "|".join(re.escape(name) for name in name_hints)
    verbs_pattern = "|".join(re.escape(verb) for verb in _FASTPATH_SPEECH_VERBS)
    punctuation_tail_pattern = r"[：:，,\s。！？!?；;]*"
    modifier_pattern = r"(?P<modifier>[\u4e00-\u9fff]{0,6}地)?"
    prefix_match = re.fullmatch(
        rf"\s*(?P<speaker>{names_pattern})\s*{modifier_pattern}\s*(?P<verb>{verbs_pattern}){punctuation_tail_pattern}",
        context.prefix_text,
    )
    suffix_match = re.match(
        rf"[：:，,\s]*(?P<speaker>{names_pattern})\s*{modifier_pattern}\s*(?P<verb>{verbs_pattern})"
        rf"{punctuation_tail_pattern}",
        context.suffix_text,
    )
    return prefix_match, suffix_match


def _is_safe_fastpath_modifier(modifier_text: str, name_hints: list[str]) -> bool:
    """
    判断 speech tag 中名字与说话动词之间的修饰语是否安全。
    """
    normalized = modifier_text.strip()
    if not normalized:
        return True
    if any(marker in normalized for marker in _FASTPATH_DIRECTIONAL_MARKERS):
        return False
    if any(marker in normalized for marker in _FASTPATH_COLLECTIVE_MARKERS):
        return False
    if any(marker in normalized for marker in _FASTPATH_PRONOUN_MARKERS):
        return False
    if _collect_unique_names(normalized, name_hints):
        return False
    return True


def _evaluate_proof_only_fastpath(
    context: _QuoteContext,
    name_hints: list[str],
) -> _FastpathEvaluation:
    """
    判断单个候选是否满足 proof-only fastpath。
    """
    if not name_hints:
        return _FastpathEvaluation(record=None, reject_reason="no_name_hints")

    prefix_match, suffix_match = _build_fastpath_speech_tag_matches(context, name_hints)

    speaker: str | None = None
    hit_type: str | None = None
    proof_segment: str | None = None
    modifier_text = ""
    if prefix_match:
        speaker = prefix_match.group("speaker")
        hit_type = "prefix_speech_verb"
        proof_segment = prefix_match.group(0)
        modifier_text = prefix_match.group("modifier") or ""
    elif suffix_match:
        speaker = suffix_match.group("speaker")
        hit_type = "suffix_speech_verb"
        proof_segment = suffix_match.group(0)
        modifier_text = suffix_match.group("modifier") or ""
    else:
        outside_quote_text = f"{context.prefix_text}{context.suffix_text}"
        unique_names = _collect_unique_names(outside_quote_text, name_hints)
        has_collective_marker = any(
            marker in context.prefix_text or marker in context.suffix_text for marker in _FASTPATH_COLLECTIVE_MARKERS
        )
        if has_collective_marker:
            return _FastpathEvaluation(record=None, reject_reason="collective_speaker")
        has_pronoun_marker = any(
            marker in context.prefix_text or marker in context.suffix_text for marker in _FASTPATH_PRONOUN_MARKERS
        )
        if has_pronoun_marker:
            return _FastpathEvaluation(record=None, reject_reason="pronoun_context")
        if not unique_names:
            return _FastpathEvaluation(record=None, reject_reason="no_explicit_name")
        if len(unique_names) > 1:
            return _FastpathEvaluation(record=None, reject_reason="multiple_names")
        return _FastpathEvaluation(record=None, reject_reason="no_strict_match")

    if proof_segment is None:
        return _FastpathEvaluation(record=None, reject_reason="no_strict_match")
    if not _is_safe_fastpath_modifier(modifier_text, name_hints):
        return _FastpathEvaluation(record=None, reject_reason="no_strict_match")
    if any(marker in proof_segment for marker in _FASTPATH_COLLECTIVE_MARKERS):
        return _FastpathEvaluation(record=None, reject_reason="collective_speaker")
    if any(marker in proof_segment for marker in _FASTPATH_PRONOUN_MARKERS):
        return _FastpathEvaluation(record=None, reject_reason="pronoun_context")
    unique_names = _collect_unique_names(proof_segment, name_hints)
    if not unique_names:
        return _FastpathEvaluation(record=None, reject_reason="no_explicit_name")
    if len(unique_names) > 1:
        return _FastpathEvaluation(record=None, reject_reason="multiple_names")
    if speaker in _FASTPATH_COLLECTIVE_MARKERS:
        return _FastpathEvaluation(record=None, reject_reason="collective_speaker")
    if speaker in _FASTPATH_PRONOUN_MARKERS:
        return _FastpathEvaluation(record=None, reject_reason="pronoun_context")
    if speaker not in unique_names:
        return _FastpathEvaluation(record=None, reject_reason="speaker_name_mismatch")

    return _FastpathEvaluation(
        record=DialogueRecordSchema(
            index=context.index,
            is_dialogue=True,
            speaker=[speaker],
            tone=None,
            is_inner_monologue=False,
            identity_clue=None,
        ),
        hit_type=hit_type,
    )


def _resolve_phase3_fastpath_candidates(
    chunk_text: str,
    candidates: list[QuoteCandidate],
    known_characters: list[str] | None,
    alias_map: dict[str, str] | None,
) -> tuple[list[DialogueRecordSchema], list[QuoteCandidate], Counter[str], Counter[str]]:
    """
    将候选拆分为 fastpath 命中和需要走 LLM 的两组。
    """
    contexts = _build_quote_contexts(chunk_text)
    name_hints = _build_fastpath_name_hints(known_characters, alias_map)
    hit_types: Counter[str] = Counter()
    reject_reasons: Counter[str] = Counter()
    fastpath_records: list[DialogueRecordSchema] = []
    llm_candidates: list[QuoteCandidate] = []

    for candidate in candidates:
        context = contexts.get(candidate.index)
        if context is None:
            llm_candidates.append(candidate)
            reject_reasons["no_quote_context"] += 1
            continue

        evaluation = _evaluate_proof_only_fastpath(context, name_hints)
        if evaluation.record is None:
            llm_candidates.append(candidate)
            reject_reasons[evaluation.reject_reason or "unknown_reject_reason"] += 1
            continue

        fastpath_records.append(evaluation.record)
        hit_types[evaluation.hit_type or "unknown_hit_type"] += 1

    return fastpath_records, llm_candidates, hit_types, reject_reasons


def _collect_fastpath_metadata_candidates(
    fastpath_records: list[DialogueRecordSchema],
    candidates: list[QuoteCandidate],
) -> list[QuoteCandidate]:
    """
    收集需要补充 metadata 的 fastpath 命中候选。
    """
    candidate_by_index = {candidate.index: candidate for candidate in candidates}
    return [candidate_by_index[record.index] for record in fastpath_records if record.index in candidate_by_index]


def _collect_fastpath_metadata_known_characters(
    fastpath_records: list[DialogueRecordSchema],
    batch_candidates: list[QuoteCandidate],
    fallback_known_characters: list[str] | None,
) -> list[str] | None:
    """
    为 fastpath metadata enrichment 收敛当前 batch 的已知说话者提示。
    """
    speaker_by_index = {record.index: record.speaker or [] for record in fastpath_records}
    ordered_speakers: list[str] = []
    for candidate in batch_candidates:
        for speaker in speaker_by_index.get(candidate.index, []):
            if speaker and speaker not in ordered_speakers:
                ordered_speakers.append(speaker)
    return ordered_speakers or fallback_known_characters


def _merge_fastpath_metadata_records(
    fastpath_records: list[DialogueRecord],
    metadata_records: list[DialogueRecord],
    require_tones: bool,
    require_identity_clues: bool,
) -> list[DialogueRecord]:
    """
    将 LLM metadata enrichment 结果合并回 fastpath 记录。
    """
    metadata_by_index = {record.index: record for record in metadata_records}
    merged_records: list[DialogueRecord] = []

    for record in fastpath_records:
        metadata_record = metadata_by_index.get(record.index)
        if metadata_record is None:
            merged_records.append(record)
            continue

        merged_records.append(
            record.model_copy(
                update={
                    "tone": metadata_record.tone if require_tones and metadata_record.tone else record.tone,
                    "identity_clue": (
                        metadata_record.identity_clue
                        if require_identity_clues and metadata_record.identity_clue
                        else record.identity_clue
                    ),
                }
            )
        )

    return merged_records


async def _gather_batch_tasks_or_cancel(
    tasks: list[asyncio.Task[tuple[str, int, list[DialogueRecord]]]],
) -> list[tuple[str, int, list[DialogueRecord]]]:
    """
    收集并行 batch 结果，并在首个失败时取消其余任务。
    """
    if not tasks:
        return []

    pending: set[asyncio.Task[tuple[str, int, list[DialogueRecord]]]] = set(tasks)
    completed_results: list[tuple[str, int, list[DialogueRecord]]] = []

    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_EXCEPTION)
            failure: BaseException | None = None
            for task in done:
                try:
                    completed_results.append(task.result())
                except BaseException as exc:  # noqa: BLE001
                    failure = exc
                    break

            if failure is not None:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                raise failure

        return completed_results
    except BaseException:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        raise


def _build_phase3_parallel_stream_id(chunk_id: int | None, batch_index: int) -> str:
    """
    为 Phase3 并行 batch 生成稳定的流分组标识。
    """
    chunk_token = chunk_id if chunk_id is not None else "global"
    return f"phase3-{chunk_token}-{batch_index + 1}"


def _clone_annotation_client_for_parallel(
    client: AnnotationClient,
    stream_id: str | None = None,
) -> AnnotationClient:
    """
    为并行 batch 构造无共享 session 的轻量客户端副本。
    """
    if client.__class__.__module__.startswith("unittest.mock"):
        return client

    task_type = getattr(client, "_task_type", None)
    raw_client = getattr(client, "_client", None)
    if task_type is None or raw_client is None:
        return client

    cloned_client = client.__class__(
        task_type=task_type,
        config=client._config,
        client=raw_client,
        analysis_logger=getattr(client, "_analysis_logger", None),
        token_usage_callback=getattr(client, "_token_usage_callback", None),
        novel_id=getattr(client, "_novel_id", None),
        session=None,
    )
    if hasattr(client, "_emitter"):
        parent_emitter = getattr(client, "_emitter", None)
        if callable(parent_emitter) and stream_id:
            async def _emit_with_stream_id(event: StreamEvent) -> None:
                # 只有真正的 LLM 文本/思维片段才需要分流；阶段级进度事件仍保留原来的 chunk 级单流语义。
                if event.action in {"output", "thinking"} and not event.stream_id:
                    event = replace(event, stream_id=stream_id)
                await parent_emitter(event)

            cloned_client._emitter = _emit_with_stream_id
        else:
            cloned_client._emitter = parent_emitter
    return cloned_client


def extract_dialogues_from_text(text: str, context_chars: int = 50) -> list[QuoteCandidate]:
    """
    从文本中提取所有引号候选及其上下文

    说明: 使用正则提取所有双引号包裹的对话内容

    Args:
        text: 原文文本
        context_chars: 上下文字符数（已废弃，LLM 有完整 chunk_text）

    Returns:
        QuoteCandidate 列表，包含 index, content
    """
    candidates: list[QuoteCandidate] = []
    for match in _collect_quote_matches(text):
        if match.content:
            candidates.append(QuoteCandidate(index=match.index, content=match.content))
    return candidates


def _collect_priority_candidate_names(
    evidence_bundle: EvidenceBundle | None,
    batch_candidates: list[QuoteCandidate],
) -> list[str] | None:
    """
    收集当前 batch 真正提到的优先候选名。

    说明: 只把当前 batch 文本里出现过的候选名上推给 evidence renderer，避免前几个候选长期占满共享证据窗口。
    """
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
    require_tones: bool = False,
    require_identity_clues: bool = False,
) -> list[DialogueRecord]:
    """
    使用 LLM 判断对话候选是否是对话，并识别说话者和语气

    说明: 调用 LLM 根据上下文判断每段对话的说话者
    """
    if not candidates:
        return []

    config = client._config
    if not config.model:
        raise ValueError("model is required")

    batch_size = settings.thinking.phase3_candidates_per_batch
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
        raise ValueError("thinking.phase3_candidates_per_batch 必须是大于等于 1 的整数")
    batch_parallelism = settings.thinking.phase3_batch_parallelism
    if not isinstance(batch_parallelism, int) or isinstance(batch_parallelism, bool) or batch_parallelism < 1:
        raise ValueError("thinking.phase3_batch_parallelism 必须是大于等于 1 的整数")

    async def _execute_single_batch(
        current_client: AnnotationClient,
        batch_candidates: list[QuoteCandidate],
        batch_idx: int,
        total_batches: int,
        attempt_number: int,
        batch_known_characters: list[str] | None = None,
        include_evidence: bool = True,
        batch_label: str = "dialogue_attribution",
    ) -> list[DialogueRecordSchema]:
        dialogue_list = "\n".join([f'{c.index}. content: "{c.content}"' for c in batch_candidates])
        effective_known_characters = batch_known_characters if batch_known_characters is not None else known_characters
        known_chars = "、".join(effective_known_characters) if effective_known_characters else "无"
        evidence_sections: list[str] = []
        if include_evidence:
            # Phase3 的共享 evidence 需要按当前 batch 重新裁剪，
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
            # Phase3 只消费上游已经准备好的共享 evidence blocks，
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
                attempt_number=attempt_number,
            ),
        )
        parsed = call_result.parsed

        logger.info(
            f"{batch_label} batch: "
            f"batch={batch_idx + 1}/{total_batches} "
            f"candidates={len(batch_candidates)} "
            f"result_count={len(parsed.dialogues)}"
        )

        return parsed.dialogues

    async def _execute_all_batches(
        current_client: AnnotationClient,
    ) -> list[DialogueRecord]:
        fastpath_records, llm_candidates, hit_types, reject_reasons = _resolve_phase3_fastpath_candidates(
            chunk_text=chunk_text,
            candidates=candidates,
            known_characters=known_characters,
            alias_map=alias_map,
        )
        metadata_candidates = (
            _collect_fastpath_metadata_candidates(fastpath_records, candidates)
            if (require_tones or require_identity_clues)
            else []
        )
        logger.info(
            "phase3_fastpath summary: chunk_id={} hits={} fallbacks={} hit_types={} reject_reasons={}",
            chunk_id,
            len(fastpath_records),
            len(llm_candidates),
            dict(sorted(hit_types.items())),
            dict(sorted(reject_reasons.items())),
        )

        validated_fastpath_records = _post_process_validation(
            fastpath_records,
            candidates,
            known_characters,
            alias_map,
            chunk_id,
        )
        if not llm_candidates and not metadata_candidates:
            return validated_fastpath_records

        semaphore = asyncio.Semaphore(batch_parallelism)

        async def _run_single_batched_retry(
            batch_idx: int,
            batch_candidates: list[QuoteCandidate],
            *,
            batch_label: str,
            total_batches: int,
            batch_known_characters: list[str] | None = None,
            include_evidence: bool = True,
            stream_id: str | None = None,
        ) -> tuple[str, int, list[DialogueRecord]]:
            async with semaphore:
                phase3_max_retries = settings.runtime.annotation.phase3_max_retries
                if not isinstance(phase3_max_retries, int) or phase3_max_retries < 1:
                    phase3_max_retries = 3
                retry_config = RetryConfig(
                    max_retries=phase3_max_retries,
                    operation_name=f"{batch_label}_batch_{batch_idx}",
                    chunk_id=chunk_id,
                )
                # 并行 worker 复用同一个 SDK client，但显式去掉 _session，
                # 避免多个 batch 协程同时写同一个 SQLAlchemy session。
                primary_worker = _clone_annotation_client_for_parallel(current_client, stream_id=stream_id)
                fallback_worker = (
                    _clone_annotation_client_for_parallel(fallback_client, stream_id=stream_id)
                    if fallback_client is not None
                    else None
                )
                retry_handler: AnnotationRetryHandler[list[DialogueRecordSchema]] = AnnotationRetryHandler(
                    config=retry_config,
                    primary_client=primary_worker,
                    fallback_client=fallback_worker,
                    exception_type=DialogueAttributionError,
                )

                async def batch_operation(
                    working_client: AnnotationClient,
                    bc: list[QuoteCandidate] = batch_candidates,
                    bi: int = batch_idx,
                    tb: int = total_batches,
                ) -> list[DialogueRecordSchema]:
                    # 重试器可能把执行客户端切到 fallback_worker，这里必须消费传入的 working_client，
                    # 不能闭包捕获 primary_worker，否则兜底分支仍会错误走主客户端。
                    return await _execute_single_batch(
                        working_client,
                        bc,
                        bi,
                        tb,
                        retry_handler.state.attempt,
                        batch_known_characters=batch_known_characters,
                        include_evidence=include_evidence,
                        batch_label=batch_label,
                    )

                batch_results = await retry_handler.execute(batch_operation)
                # 每个 batch 都必须先按自己的候选集合校验返回 index，
                # 避免跨 batch 的全局合法 index 在最终汇总时混进错误结果。
                batch_records = _post_process_validation(
                    batch_results or [],
                    batch_candidates,
                    known_characters,
                    alias_map,
                    chunk_id,
                )
                return batch_label, batch_idx, batch_records

        llm_total_batches = (len(llm_candidates) + batch_size - 1) // batch_size if llm_candidates else 0
        metadata_total_batches = (len(metadata_candidates) + batch_size - 1) // batch_size if metadata_candidates else 0

        llm_tasks: list[asyncio.Task[tuple[str, int, list[DialogueRecord]]]] = [
            asyncio.create_task(
                _run_single_batched_retry(
                    batch_idx=i // batch_size,
                    batch_candidates=llm_candidates[i : i + batch_size],
                    batch_label="phase3_dialogue_attribution",
                    total_batches=llm_total_batches,
                    stream_id=_build_phase3_parallel_stream_id(chunk_id, i // batch_size),
                )
            )
            for i in range(0, len(llm_candidates), batch_size)
        ]
        metadata_tasks: list[asyncio.Task[tuple[str, int, list[DialogueRecord]]]] = [
            asyncio.create_task(
                _run_single_batched_retry(
                    batch_idx=i // batch_size,
                    batch_candidates=metadata_candidates[i : i + batch_size],
                    batch_label="phase3_fastpath_metadata",
                    total_batches=metadata_total_batches,
                    batch_known_characters=_collect_fastpath_metadata_known_characters(
                        fastpath_records,
                        metadata_candidates[i : i + batch_size],
                        known_characters,
                    ),
                    include_evidence=False,
                    stream_id=_build_phase3_parallel_stream_id(
                        chunk_id,
                        llm_total_batches + (i // batch_size),
                    ),
                )
            )
            for i in range(0, len(metadata_candidates), batch_size)
        ]
        completed_batches = await _gather_batch_tasks_or_cancel(metadata_tasks + llm_tasks)

        metadata_records: list[DialogueRecord] = []
        llm_records: list[DialogueRecord] = []
        for batch_label, _batch_idx, batch_results in completed_batches:
            if batch_label == "phase3_fastpath_metadata":
                metadata_records.extend(batch_results)
            else:
                llm_records.extend(batch_results)

        ordered_records: list[DialogueRecord] = _merge_fastpath_metadata_records(
            validated_fastpath_records,
            metadata_records,
            require_tones=require_tones,
            require_identity_clues=require_identity_clues,
        )
        ordered_records.extend(llm_records)
        # 各 batch 已各自完成 index 校验，这里只按全局 index 排序，
        # 保证 fastpath 与 LLM 混合结果对 projector 来说仍是稳定的原文顺序。
        ordered_records.sort(key=lambda record: record.index)
        return ordered_records

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
      修正/丢弃逻辑，只保留别名归一化和日志记录
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

    说明: 调用 LLM 根据上下文判断每段对话的说话者
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
        require_tones=return_tones,
        require_identity_clues=return_identity_clues,
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
