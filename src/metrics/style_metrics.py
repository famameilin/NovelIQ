from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from src.config import settings

from .lexicon_metrics import count_mixed_hits, count_token_hits
from .text_utils import dialogue_length, split_sentences, tokenize_words

FUNCTION_WORDS_PATH = Path(__file__).parent.parent.parent / "data" / "lexicons" / "function_words.txt"

SHORT_CHUNK_TOKEN_THRESHOLD = 12
SHORT_CHUNK_MIN_POSITIVE_DENSITY = 1e-4


def load_function_words(file_path: Path | str | None = None) -> List[str]:
    if file_path is None:
        file_path = FUNCTION_WORDS_PATH
    else:
        file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"虚词词典文件不存在: {file_path}")

    words: List[str] = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                words.append(line)
    return words


SEMANTIC_CATEGORY_MAPPING = {
    "武功武器类": "combat",
    "身体部件类": "body",
    "人物关系类": "relation",
    "门派派系类": "faction",
    "使令动词类": "command",
    "动作动词类": "action",
    "心理动词类": "psychology",
    "度量形容词类": "measure",
    "情绪形容词类": "emotion",
    "色彩形容词类": "color",
}


def parse_semantic_category_lexicon(file_path: str) -> Dict[str, List[str]]:
    categories: Dict[str, List[str]] = {}
    current_category: str | None = None
    current_terms: List[str] = []
    pattern = re.compile(r"#\s*={5,}\s*(\d+)\.\s*(.+?)\s*={5,}")

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            match = pattern.match(line)
            if match:
                if current_category and current_terms:
                    categories[current_category] = current_terms
                category_name = match.group(2).strip()
                current_category = SEMANTIC_CATEGORY_MAPPING.get(category_name)
                current_terms = []
            elif not line.startswith("#") and current_category:
                current_terms.append(line)

    if current_category and current_terms:
        categories[current_category] = current_terms

    return categories


def ttr(tokens: Sequence[str]) -> float:
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


def mtld(tokens: Sequence[str], threshold: float | None = None) -> float:
    if threshold is None:
        threshold = settings.metrics.mtld_threshold
    if not tokens:
        return 0.0

    types: set[str] = set()
    factors = 0.0
    token_count = 0

    for token in tokens:
        token_count += 1
        types.add(token)
        current_ttr = len(types) / token_count
        if current_ttr <= threshold:
            factors += 1.0
            types = set()
            token_count = 0

    if token_count > 0:
        remainder_ttr = len(types) / token_count
        if remainder_ttr != 1.0:
            factors += (1.0 - remainder_ttr) / (1.0 - threshold)

    if factors == 0:
        return float(len(tokens))
    return len(tokens) / factors


def average_word_length(tokens: Sequence[str]) -> float:
    if not tokens:
        return 0.0
    return sum(len(token) for token in tokens) / len(tokens)


def word_frequency_breadth(tokens: Sequence[str], coverage: float = 0.9) -> float:
    if not tokens:
        return 0.0
    if coverage <= 0 or coverage >= 1:
        raise ValueError("coverage must be between 0 and 1")

    counts: Dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1

    total = len(tokens)
    cumulative = 0
    for _, count in sorted(counts.items(), key=lambda item: item[1], reverse=True):
        cumulative += count
        if cumulative / total >= coverage:
            break
    return (total - cumulative) / total


def function_word_distribution(tokens: Sequence[str], function_words: Iterable[str]) -> Dict[str, float]:
    total = len(tokens)
    if total == 0:
        return {}

    function_set = {word for word in function_words if word}
    counts: Dict[str, int] = {}
    for token in tokens:
        if token in function_set:
            counts[token] = counts.get(token, 0) + 1

    return {token: count / total for token, count in counts.items()}


def sentence_length_stats(text: str) -> Dict[str, float]:
    sentences = split_sentences(text)
    if not sentences:
        return {"avg_sent_len": 0.0, "sent_len_std": 0.0, "d_value": 0.0}

    lengths = [len(sentence) for sentence in sentences]
    avg = sum(lengths) / len(lengths)
    variance = sum((length - avg) ** 2 for length in lengths) / len(lengths)
    std = math.sqrt(variance)
    return {"avg_sent_len": avg, "sent_len_std": std, "d_value": std}


def pause_density(text: str) -> float:
    if not text:
        return 0.0
    pauses = len(re.findall(r"[，、；,;]", text))
    sentence_count = max(len(split_sentences(text)), 1)
    return (pauses**2) / sentence_count


def dialogue_ratio(text: str) -> float:
    if not text:
        return 0.0
    return dialogue_length(text) / len(text)


def metaphor_density(text: str) -> float:
    sentences = split_sentences(text)
    if not sentences:
        return 0.0

    markers = ("像", "如", "仿佛", "宛若", "犹如", "好似")
    hit = sum(1 for sentence in sentences if any(marker in sentence for marker in markers))
    return hit / len(sentences)


def lexicon_density(tokens: Sequence[str], terms: Iterable[str], text: str | None = None) -> float:
    total_tokens = len(tokens)
    if text is None:
        hit_count = count_token_hits(tokens, terms)
        return hit_count / max(total_tokens, 1)

    hit_count = count_mixed_hits(text, tokens, terms)
    density = hit_count / max(total_tokens, 1)

    # Keep positive density from collapsing to 0 on very short chunks.
    if hit_count > 0 and total_tokens <= SHORT_CHUNK_TOKEN_THRESHOLD:
        density = max(density, SHORT_CHUNK_MIN_POSITIVE_DENSITY)

    return density


def sensory_density(text: str, terms: Iterable[str]) -> float:
    tokens = tokenize_words(text)
    return lexicon_density(tokens, terms, text=text)


def cultural_density(text: str, terms: Iterable[str]) -> float:
    tokens = tokenize_words(text)
    return lexicon_density(tokens, terms, text=text)


def semantic_category_density(text: str, terms: Iterable[str]) -> float:
    tokens = tokenize_words(text)
    return lexicon_density(tokens, terms, text=text)


def semantic_category_densities(text: str, category_terms: Dict[str, List[str]]) -> Dict[str, float]:
    tokens = tokenize_words(text)
    total_tokens = len(tokens)
    if total_tokens == 0:
        return {key: 0.0 for key in category_terms.keys()}

    densities: Dict[str, float] = {}
    for category, terms in category_terms.items():
        if not terms:
            densities[category] = 0.0
            continue

        hit_count = count_mixed_hits(text, tokens, terms)
        density = hit_count / total_tokens
        if hit_count > 0 and total_tokens <= SHORT_CHUNK_TOKEN_THRESHOLD:
            density = max(density, SHORT_CHUNK_MIN_POSITIVE_DENSITY)
        densities[category] = density

    return densities


def imagery_density(text: str, terms: Iterable[str]) -> float:
    tokens = tokenize_words(text)
    return lexicon_density(tokens, terms, text=text)
