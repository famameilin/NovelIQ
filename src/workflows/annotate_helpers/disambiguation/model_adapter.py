"""
消歧模型调用与交互记录适配层

统一承接消歧模型调用、重试、消息构建与交互记录，避免主流程同时承担编排与审计职责。
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

from src.config import settings
from src.models.disambiguation_types import NameCountCandidate
from src.models.interfaces import DisambiguationLike
from src.models.local.disambiguation import (
    ExtendedDisambigResult,
    NameReviewState,
    build_canonical_reselect_messages,
    build_disambiguate_messages,
)


@dataclass(frozen=True)
class ModelCallSpec:
    """
    模型调用规格。

    用统一的数据结构承接“如何调用模型”和“如何记录交互”，让重试适配层不再感知具体业务阶段。
    """

    interaction_type: str
    phase: str
    build_messages: Callable[[], list[dict[str, str]]]
    invoke: Callable[[], Any]


def get_client_model_name(client: DisambiguationLike) -> str:
    """
    安全获取客户端模型名。

    轻量 fallback client 的 `_config` 可能只是占位对象，不能假定一定有 `model` 属性。
    """
    config = getattr(client, "_config", None)
    model_name = getattr(config, "model", None)
    if isinstance(model_name, str) and model_name.strip():
        return model_name
    return "unknown"


def supports_canonical_reselect(client: DisambiguationLike) -> bool:
    """
    判断客户端是否支持额外的模型代表名重选。

    fallback client 会显式声明不支持，主流程必须回退到已有 heuristic。
    """
    checker = getattr(client, "supports_canonical_reselect", None)
    if callable(checker):
        result = checker()
        if isinstance(result, bool):
            return result
    return True


def build_disambig_response_text(result: Any) -> str:
    """
    构建消歧响应文本。

    """
    if isinstance(result, ExtendedDisambigResult):
        response_dict = {
            "canonical_decisions": result.canonical_decisions,
            "alias_confidence": result.alias_confidence if hasattr(result, "alias_confidence") else {},
            "entity_types": result.entity_types if hasattr(result, "entity_types") else {},
            "entity_relations": result.entity_relations if hasattr(result, "entity_relations") else [],
            "evidence_profiles": {
                name: {
                    "has_original_sentence": profile.has_original_sentence,
                    "has_identity_clue": profile.has_identity_clue,
                    "has_summary": profile.has_summary,
                    "strong_signals": list(profile.strong_signals),
                    "strength": profile.strength,
                }
                for name, profile in getattr(result, "evidence_profiles", {}).items()
            },
        }
    elif isinstance(result, dict):
        response_dict = {
            "canonical_decisions": result,
            "alias_confidence": {},
            "entity_types": {},
            "entity_relations": [],
            "evidence_profiles": {},
        }
    else:
        response_dict = {
            "canonical_decisions": {},
            "alias_confidence": {},
            "entity_types": {},
            "entity_relations": [],
            "evidence_profiles": {},
        }

    response_dict["audit"] = get_git_audit_info()

    return json.dumps(response_dict, ensure_ascii=False)


def get_git_audit_info() -> dict[str, str]:
    """
    获取 git 审计信息。

    在模块级做缓存，避免每次模型调用都重复 fork git 子进程。
    """
    if not hasattr(get_git_audit_info, "_cache"):
        info: dict[str, str] = {}
        try:
            info["branch"] = (
                subprocess.check_output(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                .decode()
                .strip()
            )
            info["commit"] = (
                subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"],
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                .decode()
                .strip()
            )
        except Exception:
            pass
        get_git_audit_info._cache = info  # type: ignore[attr-defined]
    return get_git_audit_info._cache  # type: ignore[attr-defined]


async def call_with_recorded_retry(
    client: DisambiguationLike,
    spec: ModelCallSpec,
    *,
    run_id: str | None,
    record_interaction: Callable[..., Any],
) -> Any:
    """
    统一执行带交互记录的模型调用重试。

    将重试、耗时统计、错误记录与日志收敛到一处，业务编排层只保留阶段切换。
    """
    max_retries = settings.runtime.disambiguation.max_retries
    last_exception = None
    model_name = get_client_model_name(client)

    for attempt in range(1, max_retries + 1):
        start_time = time.time()
        messages = spec.build_messages()
        try:
            result = await spec.invoke()
            duration_ms = int((time.time() - start_time) * 1000)
            record_interaction(
                run_id=run_id,
                chunk_id=None,
                interaction_type=spec.interaction_type,
                phase=spec.phase,
                attempt_number=attempt,
                messages=messages,
                response_text=build_disambig_response_text(result),
                thinking_content=getattr(result, "_thinking_content", None),
                reasoning_tokens=getattr(result, "_reasoning_tokens", None),
                requested_thinking=getattr(getattr(client, "_config", None), "thinking_enabled", None),
                duration_ms=duration_ms,
                model_name=model_name,
                model_provider="cloud" if client.is_cloud_api() else "local",
                session=None,
            )
            return result
        except Exception as exc:
            last_exception = exc
            duration_ms = int((time.time() - start_time) * 1000)
            record_interaction(
                run_id=run_id,
                chunk_id=None,
                interaction_type=spec.interaction_type,
                phase=spec.phase,
                attempt_number=attempt,
                messages=messages,
                response_text=json.dumps({"error": str(exc)}, ensure_ascii=False),
                thinking_content=None,
                requested_thinking=getattr(getattr(client, "_config", None), "thinking_enabled", None),
                duration_ms=duration_ms,
                model_name=model_name,
                model_provider="cloud" if client.is_cloud_api() else "local",
                status="error",
                error_message=str(exc),
                session=None,
            )
            if attempt < max_retries:
                logger.warning("{} failed (attempt {}), retrying: {}", spec.phase.replace("_", " "), attempt, exc)
                time.sleep(1)
                continue

            logger.error("{} failed after {} attempts: {}", spec.phase.replace("_", " "), max_retries, exc)
            raise last_exception from None


def build_disambiguation_call_spec(
    client: DisambiguationLike,
    candidates: list[NameCountCandidate],
    context_sentences: dict[str, str],
    existing_names: list[str],
    prompt_context: Any,
    stage_name: str,
) -> ModelCallSpec:
    """
    构建普通消歧阶段的模型调用规格。

    把 prompt 构造与 invoke 细节封装为统一规格，供适配层执行。
    """

    async def _invoke() -> Any:
        return await client.disambiguate_characters(
            candidates=candidates,
            context_sentences=context_sentences,
            existing_names=existing_names if existing_names else None,
            prompt_context=prompt_context,
        )

    return ModelCallSpec(
        interaction_type="disambiguate",
        phase=stage_name.replace(" ", "_"),
        build_messages=lambda: build_disambiguate_messages(
            candidates,
            context_sentences,
            existing_names,
            prompt_context=prompt_context,
        ),
        invoke=_invoke,
    )


def build_canonical_reselect_call_spec(
    client: DisambiguationLike,
    candidates: list[NameCountCandidate],
    clusters: list[list[str]],
    context_sentences: dict[str, str],
    review_states: dict[str, NameReviewState],
    stage_name: str,
) -> ModelCallSpec:
    """
    构建最终代表名重选阶段的模型调用规格。

    将 cluster reselect 的消息构建与调用方式从主流程中抽离。
    """

    async def _invoke() -> Any:
        return await client.reselect_canonicals(
            candidates=candidates,
            clusters=clusters,
            context_sentences=context_sentences,
            review_states=review_states,
        )

    return ModelCallSpec(
        interaction_type="disambiguate",
        phase=stage_name.replace(" ", "_"),
        build_messages=lambda: build_canonical_reselect_messages(
            candidates,
            clusters,
            context_sentences=context_sentences,
            review_states=review_states,
        ),
        invoke=_invoke,
    )
