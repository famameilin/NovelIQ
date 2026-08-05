"""
旧分块伏笔解析模块归档

说明: 提取伏笔解析相关逻辑
"""

from __future__ import annotations

import re
from typing import Any, get_args

from ..schema import (
    ForeshadowingConfidence,
    ForeshadowingPayoffLikelihood,
    ForeshadowingResult,
    ForeshadowingSetupKind,
    ForeshadowingSetupStatus,
    ForeshadowingType,
)

_VALID_FORESHADOWING_TYPES = frozenset(get_args(ForeshadowingType))
_VALID_CONFIDENCES = frozenset(get_args(ForeshadowingConfidence))
_VALID_SETUP_KINDS = frozenset(get_args(ForeshadowingSetupKind))
_VALID_PAYOFF_LIKELIHOODS = frozenset(get_args(ForeshadowingPayoffLikelihood))
_VALID_SETUP_STATUSES = frozenset(get_args(ForeshadowingSetupStatus))
_HOOK_LABEL = "具体钩子："
_UNRESOLVED_LABEL = "未闭合原因："
_TRUE_BOOL_MARKERS = frozenset({"true", "1", "yes", "y", "on"})
_FALSE_BOOL_MARKERS = frozenset({"false", "0", "no", "n", "off"})


def _normalize_setup_summary_text(value: str) -> str:
    """
    归一化 setup_summary 文本，用于 exact-match 去重
    """
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).strip().lower()


def _coerce_boolean_field(field_name: str, value: Any, default: bool = False) -> bool:
    """
    严格归一化结构化输出里的布尔字段
    """
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        if value in (0, 0.0):
            return False
        if value in (1, 1.0):
            return True
        raise ValueError(f"{field_name} must be a boolean-compatible 0/1, got {value!r}")

    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return default
        if normalized in _TRUE_BOOL_MARKERS:
            return True
        if normalized in _FALSE_BOOL_MARKERS:
            return False

    raise ValueError(f"{field_name} must be a boolean, got {value!r}")


def _extract_reason_sections(reason: str) -> tuple[str | None, str | None]:
    """
    从 anchor_reason 中提取“具体钩子/未闭合原因”两段
    """
    normalized = reason.strip()
    hook_index = normalized.find(_HOOK_LABEL)
    unresolved_index = normalized.find(_UNRESOLVED_LABEL)
    if hook_index != 0 or unresolved_index <= hook_index:
        return None, None

    hook_text = normalized[len(_HOOK_LABEL) : unresolved_index].strip("；;。 \n\t")
    unresolved_text = normalized[unresolved_index + len(_UNRESOLVED_LABEL) :].strip("；;。 \n\t")
    if not hook_text or not unresolved_text:
        return None, None
    return hook_text, unresolved_text


def _has_structured_anchor_reason(result: ForeshadowingResult) -> bool:
    """
    判断 anchor_reason 是否满足正式结构合同

    修改时间: 2026-04-29
    任务: foreshadow-expectation-v2
    修改原因: Phase2 是否属于强 setup 由 LLM 在调用时判断，本地 validator 只保留
              anchor_reason 双段结构与必填字段校验，不再用词表做第二次语义裁判。
    """
    hook_text, anchor_unresolved_text = _extract_reason_sections(result.anchor_reason)
    if hook_text is None or anchor_unresolved_text is None:
        return False

    return bool(result.why_unresolved_now.strip())


def parse_foreshadowing_result(data: dict[str, Any]) -> ForeshadowingResult:
    """
    解析伏笔分析结果
    """
    raw_has_foreshadowing = _coerce_boolean_field(
        "has_foreshadowing",
        data.get("has_foreshadowing", False),
        default=False,
    )
    raw_is_strong_setup = _coerce_boolean_field(
        "is_strong_setup",
        data.get("is_strong_setup", False),
        default=False,
    )
    degrade_to_negative = raw_has_foreshadowing and not raw_is_strong_setup

    # 弱阳性是当前 Phase2 最常见的脏输出之一
    # 这里先把它归一化成 negative，再交给 validator/projector 做后续筛除，
    # 避免 schema 校验把“应丢弃的边缘样本”升级成整次 phase 失败
    has_foreshadowing = raw_has_foreshadowing and not degrade_to_negative
    is_strong_setup = raw_is_strong_setup if has_foreshadowing else False

    foreshadowing_type_raw = data.get("foreshadowing_type")
    if has_foreshadowing and foreshadowing_type_raw in _VALID_FORESHADOWING_TYPES:
        foreshadowing_type: ForeshadowingType | None = foreshadowing_type_raw
    else:
        foreshadowing_type = None

    setup_kind_raw = data.get("setup_kind")
    if has_foreshadowing and setup_kind_raw in _VALID_SETUP_KINDS:
        setup_kind: ForeshadowingSetupKind | None = setup_kind_raw
    else:
        setup_kind = None

    setup_summary = data.get("setup_summary", "") if has_foreshadowing else ""

    payoff_likelihood_raw = data.get("payoff_likelihood")
    if has_foreshadowing and payoff_likelihood_raw in _VALID_PAYOFF_LIKELIHOODS:
        payoff_likelihood: ForeshadowingPayoffLikelihood | None = payoff_likelihood_raw
    else:
        payoff_likelihood = None

    setup_status_raw = data.get("setup_status")
    if has_foreshadowing and setup_status_raw in _VALID_SETUP_STATUSES:
        setup_status: ForeshadowingSetupStatus | None = setup_status_raw
    else:
        setup_status = None

    is_new_setup = (
        _coerce_boolean_field(
            "is_new_setup",
            data.get("is_new_setup", False),
            default=False,
        )
        if has_foreshadowing
        else False
    )
    linked_setup_id_raw = data.get("linked_setup_id")
    linked_setup_id = str(linked_setup_id_raw).strip() if has_foreshadowing and linked_setup_id_raw else None

    # 强伏笔池只接受显式 high
    # provider 如果漏掉 confidence，宁可降为 low 丢弃，也不能静默补成 high 放行
    confidence_raw = data.get("confidence", "low")
    confidence: ForeshadowingConfidence = confidence_raw if confidence_raw in _VALID_CONFIDENCES else "low"
    if degrade_to_negative:
        confidence = "low"

    return ForeshadowingResult(
        has_foreshadowing=has_foreshadowing,
        is_strong_setup=is_strong_setup,
        foreshadowing_type=foreshadowing_type,
        setup_kind=setup_kind,
        anchor_text=data.get("anchor_text", ""),
        anchor_reason=data.get("anchor_reason", ""),
        setup_summary=setup_summary if has_foreshadowing else "",
        why_unresolved_now=data.get("why_unresolved_now", "") if has_foreshadowing else "",
        expected_payoff_family=data.get("expected_payoff_family", "") if has_foreshadowing else "",
        payoff_likelihood=payoff_likelihood,
        is_new_setup=is_new_setup,
        linked_setup_id=linked_setup_id,
        setup_status=setup_status,
        confidence=confidence,
    )


def validate_foreshadowing_result(result: ForeshadowingResult, chunk_text: str) -> bool:
    """
    硬校验：anchor_text 必须是原文的真实子串

    返回 False 则丢弃该条记录，不入库

    修改时间: 2026-04-29
    任务: foreshadow-expectation-v2
    修改原因: Phase2 强 setup 语义判断已交给 LLM 输出字段，本地只保留合同和结构校验，
              不再用关键词/句式规则对模型的 high/medium positive 再做二次裁决。
    """
    if not result.has_foreshadowing:
        if result.is_strong_setup:
            return False
        if result.foreshadowing_type is not None:
            return False
        if result.setup_kind is not None:
            return False
        if result.why_unresolved_now.strip():
            return False
        if result.expected_payoff_family.strip():
            return False
        return True

    if not result.is_strong_setup:
        return False

    if result.confidence not in {"high", "medium"}:
        return False

    if result.foreshadowing_type is None:
        return False

    if result.setup_kind is None:
        return False

    if not result.setup_summary or len(result.setup_summary.strip()) < 4:
        return False

    if result.payoff_likelihood is None:
        return False
    if result.payoff_likelihood == "low":
        return False

    if result.setup_status is None:
        return False

    if not result.anchor_text or len(result.anchor_text.strip()) < 5:
        return False

    if result.anchor_text not in chunk_text:
        return False

    if not result.why_unresolved_now or len(result.why_unresolved_now.strip()) < 6:
        return False

    if not result.expected_payoff_family or len(result.expected_payoff_family.strip()) < 2:
        return False

    if result.is_new_setup:
        if result.linked_setup_id is not None:
            return False
        if result.setup_status != "open":
            return False
    else:
        if not result.linked_setup_id or len(result.linked_setup_id.strip()) < 4:
            return False
        if result.setup_status not in {"reinforced", "likely_paid_off"}:
            return False

    # setup 池的 exact-match 去重要依赖标准化 summary；
    # 如果归一化后为空，说明模型没有给出真正可池化的 thread 摘要
    if not _normalize_setup_summary_text(result.setup_summary):
        return False

    return _has_structured_anchor_reason(result)
