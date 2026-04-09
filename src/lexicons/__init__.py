"""
词表模块（v2）

仅提供 LexiconRegistry 相关 API。

移除的 API（2026-04-06）:
- load_lexicon: 使用 LexiconRegistry.get() 替代
- load_all_lexicons: 使用 LexiconRegistry 替代
- match_terms: 使用 count_mixed_hits 替代
- update_lexicons_from_texts: 已移除

创建时间: 2026-04-06
修改者: GLM-5
任务: 移除向后兼容代码
"""

from .registry import LexiconRegistry, get_registry, reset_registry

__all__ = [
    "LexiconRegistry",
    "get_registry",
    "reset_registry",
]
