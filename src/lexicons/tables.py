"""
词表加载表（tables）

get 读取词表数据 -> 缓存为模块级常量 -> 消费方统一引用常量，不再各自调 registry。

2026-08-15 词表 v3：生产词表固定于 data/lexicons（registry 为唯一事实源），
消费方（段落链 / 停用词 / 语义类别）改为引用本模块常量，词表进程内加载一次；
文件名在此集中声明（无语义 key 层，表目标识即文件名）。
"""

from __future__ import annotations

from pathlib import Path

from src.lexicons.registry import LexiconRegistry
from src.metrics.style_metrics import parse_semantic_category_lexicon

_registry = LexiconRegistry()
_registry.load()

# ===== 情感（L1 核心 + L2 口语合并，统一权重 1.0 的命中计数 dict） =====
POSITIVE_TERMS: dict[str, int] = dict.fromkeys(
    _registry.get("positive.txt") + _registry.get("colloquial_positive.txt"), 1
)
NEGATIVE_TERMS: dict[str, int] = dict.fromkeys(
    _registry.get("negative.txt") + _registry.get("colloquial_negative.txt"), 1
)

# ===== 张力 =====
COMBAT_TERMS: list[str] = _registry.get("combat.txt")

# ===== 风格 =====
SENSORY_TERMS: list[str] = _registry.get("sensory.txt")
FUNCTION_WORDS_TERMS: list[str] = _registry.get("function_words.txt")
IMAGERY_TERMS: list[str] = _registry.get("imagery.txt")
SEMANTIC_CATEGORY_FILE: Path = _registry.get_file_paths("semantic_category.txt")[0]
SEMANTIC_CATEGORIES: dict[str, list[str]] = parse_semantic_category_lexicon(str(SEMANTIC_CATEGORY_FILE))

# ===== tokenizer 类 =====
STOPWORDS_TERMS: list[str] = _registry.get("stopwords.txt")
