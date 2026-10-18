"""
词表模块

仅提供 LexiconRegistry 相关 API
"""

from .registry import LexiconRegistry, get_registry, reset_registry

__all__ = [
    "LexiconRegistry",
    "get_registry",
    "reset_registry",
]
