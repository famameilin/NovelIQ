"""语言风格扩展指标。"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from collections.abc import Iterable

import jieba

from src.config import settings
from src.text_processing.text_utils import tokenize_words
from src.text_processing.tokenize import get_tokenizer, is_tokenizer_initialized

from .lexicon_metrics import GroupedMixedMatcher

FUNCTION_WORDS = {
    "之",
    "其",
    "者",
    "也",
    "所",
    "以",
    "而",
    "与",
    "则",
    "乃",
    "于",
    "乎",
    "矣",
    "焉",
    "哉",
    "兮",
    "尔",
    "若",
    "为",
    "何",
}

SEMANTIC_CATEGORY_KEYS = [
    "combat",
    "body",
    "relation",
    "faction",
    "command",
    "action",
    "psychology",
    "measure",
    "emotion",
    "color",
]


def compute_string_token_diversity(
    all_tokens: list[str],
) -> float | None:
    """连续汉字/拉丁串去重率（不是 jieba 分词 TTR）"""
    if not all_tokens:
        return None

    total_tokens = len(all_tokens)
    unique_tokens = len(set(all_tokens))

    return unique_tokens / (total_tokens + 1e-6)


def compute_avg_word_len(
    texts: list[str],
) -> float:
    if not texts:
        return 0.0

    all_words: list[str] = []
    for text in texts:
        words = list(jieba.cut(text))
        all_words.extend([w for w in words if w.strip()])

    if not all_words:
        return 0.0

    total_len = sum(len(word) for word in all_words)
    total_words = len(all_words)

    return total_len / (total_words + 1e-6)


def compute_sent_len_std(
    texts: list[str],
) -> float | None:
    if not texts:
        return None

    all_sentences = []
    for text in texts:
        sentences = re.split(r"[。！？\n]", text)
        for sent in sentences:
            sent = sent.strip()
            if sent:
                all_sentences.append(sent)

    if len(all_sentences) < 2:
        return None

    sent_lengths = [len(sent) for sent in all_sentences]

    # 总体方差口径，与 /chapter-metrics 的充分统计量一致
    return statistics.pstdev(sent_lengths)


def compute_function_word_vector(
    texts: list[str],
) -> dict[str, float] | None:
    if not texts:
        return None

    total_chars = sum(len(text) for text in texts)
    if total_chars == 0:
        return None
    # 虚字指纹需要足够文本量，短书输出 None（禁止 0 值伪装）
    if total_chars < settings.metrics.function_word_min_chars:
        return None

    all_chars = []
    for text in texts:
        all_chars.extend([c for c in text if c in FUNCTION_WORDS])

    counts = Counter(all_chars)

    return {word: counts.get(word, 0) / total_chars for word in FUNCTION_WORDS}


def _load_semantic_categories() -> dict[str, list[str]]:
    """加载语义类别词表（经 tables 常量 registry 一次性读取）。"""
    from src.lexicons.tables import SEMANTIC_CATEGORIES

    return {key: SEMANTIC_CATEGORIES.get(key, []) for key in SEMANTIC_CATEGORY_KEYS}


def compute_category_density(
    texts: list[str],
) -> dict[str, float]:
    """统计各语义类别的词元密度"""
    return _category_density((text, tokenize_words(text)) for text in texts if text)


def _category_density(segmented: Iterable[tuple[str, list[str]]]) -> dict[str, float]:
    category_terms = _load_semantic_categories()
    total_tokens = 0
    category_hits = dict.fromkeys(category_terms.keys(), 0)
    matcher = GroupedMixedMatcher(category_terms)

    for text, tokens in segmented:
        total_tokens += len(tokens)

        if not tokens:
            continue

        for category, hits in matcher.count(text, tokens).items():
            category_hits[category] += hits

    if total_tokens == 0:
        return dict.fromkeys(category_terms.keys(), 0.0)

    result = {}
    for category, hit_count in category_hits.items():
        result[category] = min(hit_count / total_tokens, 1.0)

    return result


def compute_word_style(texts: list[str]) -> tuple[float, dict[str, float]]:
    """项目词典已加载时，平均词长与语义类别共享同一次切词"""
    if not is_tokenizer_initialized():
        return compute_avg_word_len(texts), compute_category_density(texts)

    tokenizer = get_tokenizer()
    word_count = 0
    total_length = 0

    def segmented() -> Iterable[tuple[str, list[str]]]:
        nonlocal word_count, total_length
        for text in texts:
            if text:
                tokens, count, length = tokenizer.tokenize_with_word_lengths(text)
                word_count += count
                total_length += length
                yield text, tokens

    densities = _category_density(segmented())
    average_length = total_length / (word_count + 1e-6) if word_count else 0.0
    return average_length, densities
