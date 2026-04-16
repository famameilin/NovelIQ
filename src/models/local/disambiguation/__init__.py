"""
消歧模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
说明: 人名消歧相关功能模块

修改时间: 2026-03-27
修改者: TraeAI
任务: disambiguation-state-three-layer
修改内容: 新增 NameReviewState、DisambiguationState、validate_state_invariants 导出

修改时间: 2026-04-16
修改者: Codex
任务: trim-legacy-string-evidence
修改内容: 改为 lazy export，避免 package 顶层导出触发循环导入
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .api_call import call_disambiguate_api
    from .evidence import EvidenceProfile, build_evidence_profile, format_evidence_profile
    from .evidence_renderer import (
        render_disambig_candidates,
        render_disambig_prompt_context,
    )
    from .logging import (
        log_disambiguate_response,
        log_disambiguate_result,
        log_disambiguate_start,
    )
    from .messages import (
        build_anonymous_disambig_messages,
        build_disambiguate_messages,
        build_existing_character_hint,
    )
    from .result_builder import ExtendedDisambigResult, build_extended_result_from_response, build_result_from_response
    from .state import (
        DisambiguationState,
        NameReviewState,
        validate_state_invariants,
    )


_EXPORTS: dict[str, tuple[str, str]] = {
    "call_disambiguate_api": (".api_call", "call_disambiguate_api"),
    "EvidenceProfile": (".evidence", "EvidenceProfile"),
    "build_evidence_profile": (".evidence", "build_evidence_profile"),
    "format_evidence_profile": (".evidence", "format_evidence_profile"),
    "render_disambig_candidates": (".evidence_renderer", "render_disambig_candidates"),
    "render_disambig_prompt_context": (".evidence_renderer", "render_disambig_prompt_context"),
    "log_disambiguate_response": (".logging", "log_disambiguate_response"),
    "log_disambiguate_result": (".logging", "log_disambiguate_result"),
    "log_disambiguate_start": (".logging", "log_disambiguate_start"),
    "build_anonymous_disambig_messages": (".messages", "build_anonymous_disambig_messages"),
    "build_disambiguate_messages": (".messages", "build_disambiguate_messages"),
    "build_existing_character_hint": (".messages", "build_existing_character_hint"),
    "ExtendedDisambigResult": (".result_builder", "ExtendedDisambigResult"),
    "build_extended_result_from_response": (".result_builder", "build_extended_result_from_response"),
    "build_result_from_response": (".result_builder", "build_result_from_response"),
    "DisambiguationState": (".state", "DisambiguationState"),
    "NameReviewState": (".state", "NameReviewState"),
    "validate_state_invariants": (".state", "validate_state_invariants"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    # 中文注释：按需导入子模块，既保留 `from ... import X` 的兼容接口，
    # 也避免 `__init__` 在包初始化阶段把整条消歧依赖链一次性拉起。
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_EXPORTS.keys()))


__all__ = list(_EXPORTS.keys())
