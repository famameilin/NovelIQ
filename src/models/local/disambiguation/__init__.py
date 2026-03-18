"""
消歧模块

创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - Task 9 拆分disambiguation_client.py
说明: 人名消歧相关功能模块
"""

from __future__ import annotations

from .api_call import call_disambiguate_api
from .logging import (
    log_disambiguate_response,
    log_disambiguate_result,
    log_disambiguate_start,
)
from .messages import (
    build_anonymous_disambig_messages,
    build_disambiguate_messages,
)
from .result_builder import build_result_from_response

__all__ = [
    # messages
    "build_disambiguate_messages",
    "build_anonymous_disambig_messages",
    # result_builder
    "build_result_from_response",
    # logging
    "log_disambiguate_start",
    "log_disambiguate_response",
    "log_disambiguate_result",
    # api_call
    "call_disambiguate_api",
]
