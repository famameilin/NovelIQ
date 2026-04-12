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
"""

from __future__ import annotations

from .api_call import call_disambiguate_api
from .evidence import EvidenceProfile, build_evidence_profile, format_evidence_profile
from .evidence_renderer import (
    render_disambig_candidates,
    render_disambig_prompt_context,
    render_graph_feedback_hint,
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

__all__ = [
    # messages
    "build_disambiguate_messages",
    "build_anonymous_disambig_messages",
    "build_existing_character_hint",
    "build_evidence_profile",
    "format_evidence_profile",
    "EvidenceProfile",
    "render_disambig_candidates",
    "render_disambig_prompt_context",
    "render_graph_feedback_hint",
    # result_builder
    "build_result_from_response",
    "build_extended_result_from_response",
    "ExtendedDisambigResult",
    # logging
    "log_disambiguate_start",
    "log_disambiguate_response",
    "log_disambiguate_result",
    # api_call
    "call_disambiguate_api",
    # state
    "NameReviewState",
    "DisambiguationState",
    "validate_state_invariants",
]
