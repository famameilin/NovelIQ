"""
消歧共享常量。

创建时间: 2026-04-21
创建者: Codex
任务: fix-disambig-protected-constants
说明: 收敛 protected 候选在 prompt / pipeline / gate 中复用的文案常量，
      避免多个模块各自硬编码同一前缀，后续改文案时出现语义漂移。
"""

from __future__ import annotations

PROTECTED_CATEGORY_LABEL = "受保护-默认不合并"
PROTECTED_CONTEXT_PREFIX = f"【{PROTECTED_CATEGORY_LABEL}】"
