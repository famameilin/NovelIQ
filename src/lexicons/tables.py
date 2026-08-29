"""
词表加载表（tables）

get 读取词表数据 -> 缓存为模块级常量 -> 消费方统一引用常量，不再各自调 registry。

2026-08-15 词表 v3：生产词表固定于 data/lexicons（registry 为唯一事实源），
消费方（段落链 / 停用词 / 语义类别）改为引用本模块常量，词表进程内加载一次；
文件名经 constants.LEXICON_FILES 语义 key 引用（2026-08-28 常量化）。
"""

from __future__ import annotations

from pathlib import Path

from src.config.constants import LEXICON_FILES
from src.lexicons.registry import LexiconRegistry
from src.metrics.style_metrics import parse_semantic_category_lexicon

_registry = LexiconRegistry()
_registry.load()

# ===== 情感（L1 核心 + L2 口语合并，统一权重 1.0 的命中计数 dict） =====
POSITIVE_TERMS: dict[str, int] = dict.fromkeys(
    _registry.get(LEXICON_FILES["positive"]) + _registry.get(LEXICON_FILES["colloquial_positive"]), 1
)
NEGATIVE_TERMS: dict[str, int] = dict.fromkeys(
    _registry.get(LEXICON_FILES["negative"]) + _registry.get(LEXICON_FILES["colloquial_negative"]), 1
)

# ===== 张力 =====
COMBAT_TERMS: list[str] = _registry.get(LEXICON_FILES["combat"])

# ===== 风格 =====
SENSORY_TERMS: list[str] = _registry.get(LEXICON_FILES["sensory"])
FUNCTION_WORDS_TERMS: list[str] = _registry.get(LEXICON_FILES["function_words"])
IMAGERY_TERMS: list[str] = _registry.get(LEXICON_FILES["imagery"])
SEMANTIC_CATEGORY_FILE: Path = _registry.get_file_paths(LEXICON_FILES["semantic_category"])[0]
SEMANTIC_CATEGORIES: dict[str, list[str]] = parse_semantic_category_lexicon(str(SEMANTIC_CATEGORY_FILE))

# ===== tokenizer 类 =====
STOPWORDS_TERMS: list[str] = _registry.get(LEXICON_FILES["stopwords"])
