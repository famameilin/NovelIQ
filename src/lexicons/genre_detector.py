"""
小说类型自动检测模块

根据领域词表命中模式自动识别小说类型。

支持的类型:
- xianxia: 修仙/仙侠类
- urban: 都市/言情类
- power: 权谋/宫斗类
- shuwen: 爽文/快节奏类
- general: 通用/无法确定

创建时间: 2026-04-06
创建者: GLM-5
任务: 词表与张力信号系统重构 - Task 10

修改时间: 2026-04-06
修改者: GLM-5
任务: 类型检测模块修复
修改内容:
  - P0: indicators 纳入得分计算，权重为词表的 2 倍
  - P1: 新增分段检测功能，支持类型序列输出

修改时间: 2026-04-06
修改者: GLM-5
任务: 代码审查问题修复
修改内容: 添加低置信度检测日志输出，便于后续调优
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from src.lexicons.registry import LexiconRegistry
from src.metrics.text_utils import tokenize_words

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class GenreDetectionResult:
    """类型检测结果"""

    genre: str
    confidence: float
    scores: dict[str, float]
    top_indicators: list[str]


@dataclass
class SegmentGenreResult:
    """分段类型检测结果"""

    segment_index: int
    start_char: int
    end_char: int
    genre: str
    confidence: float
    scores: dict[str, float]
    top_indicators: list[str]


@dataclass
class GenreSequenceResult:
    """类型序列检测结果"""

    segments: list[SegmentGenreResult]
    genre_distribution: dict[str, float]
    dominant_genre: str
    genre_transitions: list[tuple[int, str, str]]


DOMAIN_KEYWORDS = {
    "xianxia": {
        "positive": ["xianxia_positive"],
        "negative": ["xianxia_negative"],
        "indicators": [
            "剑气",
            "真气",
            "灵力",
            "修仙",
            "境界",
            "丹药",
            "法宝",
            "渡劫",
            "筑基",
            "金丹",
            "元婴",
            "化神",
            "飞升",
            "仙界",
            "妖兽",
            "宗门",
            "弟子",
            "师尊",
            "道友",
        ],
    },
    "urban": {
        "positive": ["urban_positive"],
        "negative": ["urban_negative"],
        "indicators": [
            "表白",
            "求婚",
            "分手",
            "职场",
            "升职",
            "创业",
            "恋爱",
            "公司",
            "老板",
            "同事",
            "面试",
            "加班",
            "工资",
            "合同",
            "项目",
            "客户",
        ],
    },
    "power": {
        "negative": ["power_struggle"],
        "indicators": [
            "权谋",
            "阴谋",
            "暗杀",
            "夺权",
            "篡位",
            "朝堂",
            "皇帝",
            "大臣",
            "宫斗",
            "皇后",
            "妃子",
            "太子",
            "王爷",
            "将军",
            "谋反",
        ],
    },
    "shuwen": {
        "positive": ["shuwen_pattern"],
        "indicators": [
            "打脸",
            "逆袭",
            "装逼",
            "爽",
            "逆袭",
            "碾压",
            "震惊",
            "跪了",
            "服了",
            "天才",
            "废物",
            "天才变废物",
            "废物变天才",
        ],
    },
    "scifi": {
        "indicators": [
            "星际",
            "太空",
            "宇宙",
            "星系",
            "飞船",
            "机甲",
            "机器人",
            "人工智能",
            "AI",
            "芯片",
            "量子",
            "基因",
            "克隆",
            "联邦",
            "帝国",
            "跃迁",
            "黑洞",
            "虫洞",
        ],
    },
    "historical": {
        "indicators": [
            "朝代",
            "皇帝",
            "陛下",
            "圣上",
            "皇后",
            "妃子",
            "太子",
            "王爷",
            "将军",
            "宫斗",
            "后宫",
            "选秀",
            "册封",
            "夺嫡",
            "篡位",
            "谋反",
            "本宫",
            "本王",
            "微臣",
            "臣妾",
        ],
    },
    "mystery": {
        "indicators": [
            "案件",
            "命案",
            "凶杀案",
            "谋杀",
            "凶手",
            "嫌疑人",
            "侦探",
            "刑警",
            "法医",
            "证据",
            "线索",
            "推理",
            "破案",
            "真相",
            "谜团",
            "悬疑",
            "诡异",
            "神秘",
            "离奇",
            "反转",
        ],
    },
}

INDICATOR_WEIGHT = 2.0
MIN_CONFIDENCE = 0.3


def detect_genre(
    text: str,
    registry: LexiconRegistry | None = None,
    min_confidence: float = MIN_CONFIDENCE,
) -> GenreDetectionResult:
    """
    检测小说类型。

    Args:
        text: 待检测文本（建议使用前 5000-10000 字）
        registry: 词表注册中心（可选，默认使用全局单例）
        min_confidence: 最低置信度阈值

    Returns:
        类型检测结果
    """
    if registry is None:
        registry = LexiconRegistry()
        registry.load()

    tokens = tokenize_words(text)
    token_count = max(len(tokens), 1)

    scores: dict[str, float] = {}
    indicators_found: dict[str, list[str]] = {}

    for genre, config in DOMAIN_KEYWORDS.items():
        domain_hits = 0
        found_indicators = []

        if "positive" in config:
            for domain in config["positive"]:
                terms = registry.get_with_domains("emotion.positive", [domain])
                domain_hits += sum(1 for t in tokens if t in terms)

        if "negative" in config:
            for domain in config["negative"]:
                terms = registry.get_with_domains("emotion.negative", [domain])
                domain_hits += sum(1 for t in tokens if t in terms)

        for indicator in config.get("indicators", []):
            if indicator in text:
                found_indicators.append(indicator)

        indicator_hits = len(found_indicators) * INDICATOR_WEIGHT
        scores[genre] = (domain_hits + indicator_hits) / token_count
        indicators_found[genre] = found_indicators

    total_score = sum(scores.values())
    if total_score > 0:
        normalized_scores = {k: v / total_score for k, v in scores.items()}
    else:
        normalized_scores = dict.fromkeys(scores, 0.0)

    best_genre = max(normalized_scores.keys(), key=lambda k: normalized_scores[k])
    best_confidence = normalized_scores[best_genre]

    if best_confidence < min_confidence:
        logger.debug(
            f"Low confidence genre detection: best_genre={best_genre}, "
            f"confidence={best_confidence:.2%}, scores={normalized_scores}, "
            f"falling back to 'general'"
        )
        best_genre = "general"
        best_confidence = 0.0

    top_indicators = indicators_found.get(best_genre, [])[:5]

    return GenreDetectionResult(
        genre=best_genre,
        confidence=best_confidence,
        scores=normalized_scores,
        top_indicators=top_indicators,
    )


def detect_genre_from_file(
    file_path: Path,
    sample_size: int = 5000,
    registry: LexiconRegistry | None = None,
) -> GenreDetectionResult:
    """
    从文件检测小说类型。

    Args:
        file_path: 小说文件路径
        sample_size: 采样字数
        registry: 词表注册中心

    Returns:
        类型检测结果
    """
    encodings = ["utf-8", "gbk", "gb2312"]
    content = None

    for encoding in encodings:
        try:
            with open(file_path, encoding=encoding) as f:
                content = f.read(sample_size)
            break
        except UnicodeDecodeError:
            continue

    if content is None:
        return GenreDetectionResult(
            genre="general",
            confidence=0.0,
            scores={},
            top_indicators=[],
        )

    return detect_genre(content, registry)


def detect_genre_sequence(
    text: str,
    segment_size: int = 5000,
    overlap: int = 500,
    registry: LexiconRegistry | None = None,
) -> GenreSequenceResult:
    """
    分段检测小说类型，输出类型序列。

    用于处理"前期都市后期修仙"等类型变化的场景。

    Args:
        text: 完整文本
        segment_size: 每段字数
        overlap: 段间重叠字数
        registry: 词表注册中心

    Returns:
        类型序列检测结果
    """
    if registry is None:
        registry = LexiconRegistry()
        registry.load()

    segments: list[SegmentGenreResult] = []
    text_len = len(text)
    start = 0
    idx = 0

    while start < text_len:
        end = min(start + segment_size, text_len)
        segment_text = text[start:end]

        result = detect_genre(segment_text, registry)

        segments.append(
            SegmentGenreResult(
                segment_index=idx,
                start_char=start,
                end_char=end,
                genre=result.genre,
                confidence=result.confidence,
                scores=result.scores,
                top_indicators=result.top_indicators,
            )
        )

        start = end - overlap if end < text_len else text_len
        idx += 1

    genre_counts: dict[str, int] = {}
    for seg in segments:
        genre_counts[seg.genre] = genre_counts.get(seg.genre, 0) + 1

    total_segments = len(segments)
    genre_distribution = {g: c / total_segments for g, c in genre_counts.items() if total_segments > 0}

    dominant_genre = max(genre_distribution.keys(), key=lambda k: genre_distribution[k])

    transitions: list[tuple[int, str, str]] = []
    for i in range(1, len(segments)):
        prev_genre = segments[i - 1].genre
        curr_genre = segments[i].genre
        if prev_genre != curr_genre:
            transitions.append((segments[i].start_char, prev_genre, curr_genre))

    return GenreSequenceResult(
        segments=segments,
        genre_distribution=genre_distribution,
        dominant_genre=dominant_genre,
        genre_transitions=transitions,
    )


def detect_genre_sequence_from_file(
    file_path: Path,
    segment_size: int = 5000,
    overlap: int = 500,
    registry: LexiconRegistry | None = None,
) -> GenreSequenceResult:
    """
    从文件分段检测小说类型。

    Args:
        file_path: 小说文件路径
        segment_size: 每段字数
        overlap: 段间重叠字数
        registry: 词表注册中心

    Returns:
        类型序列检测结果
    """
    encodings = ["utf-8", "gbk", "gb2312"]
    content = None

    for encoding in encodings:
        try:
            with open(file_path, encoding=encoding) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue

    if content is None:
        return GenreSequenceResult(
            segments=[],
            genre_distribution={},
            dominant_genre="general",
            genre_transitions=[],
        )

    return detect_genre_sequence(content, segment_size, overlap, registry)


def get_recommended_lexicons(genre: str) -> dict[str, list[str]]:
    """
    根据小说类型获取推荐的词表配置。

    Args:
        genre: 小说类型

    Returns:
        推荐的词表域名映射
    """
    recommendations: dict[str, dict[str, list[str]]] = {
        "xianxia": {
            "pos_domains": ["xianxia_positive"],
            "neg_domains": ["xianxia_negative"],
            "fight_domains": [],
        },
        "urban": {
            "pos_domains": ["urban_positive"],
            "neg_domains": ["urban_negative"],
            "fight_domains": [],
        },
        "power": {
            "pos_domains": [],
            "neg_domains": ["power_struggle"],
            "fight_domains": ["power_struggle"],
        },
        "shuwen": {
            "pos_domains": ["shuwen_pattern"],
            "neg_domains": [],
            "fight_domains": [],
        },
        "scifi": {
            "pos_domains": [],
            "neg_domains": [],
            "fight_domains": [],
            "domain_lexicons": ["scifi_terms"],
        },
        "historical": {
            "pos_domains": [],
            "neg_domains": ["power_struggle"],
            "fight_domains": ["power_struggle"],
            "domain_lexicons": ["historical_terms"],
        },
        "mystery": {
            "pos_domains": [],
            "neg_domains": [],
            "fight_domains": [],
            "domain_lexicons": ["mystery_terms"],
        },
        "general": {
            "pos_domains": [],
            "neg_domains": [],
            "fight_domains": [],
        },
    }

    return recommendations.get(genre, recommendations["general"])


def get_dynamic_lexicons(
    text: str,
    registry: LexiconRegistry | None = None,
) -> dict[str, set[str]]:
    """
    根据文本内容动态检测类型并加载对应词表。

    用于处理"前期都市后期修仙"等类型变化的场景。

    Args:
        text: 待分析文本
        registry: 词表注册中心

    Returns:
        动态加载的词表集合
    """
    if registry is None:
        registry = LexiconRegistry()
        registry.load()

    result = detect_genre(text, registry)
    config = get_recommended_lexicons(result.genre)

    lexicons: dict[str, set[str]] = {
        "pos_terms": set(),
        "neg_terms": set(),
        "fight_terms": set(),
    }

    for domain in config.get("pos_domains", []):
        terms = registry.get_with_domains("emotion.positive", [domain])
        lexicons["pos_terms"].update(terms)

    for domain in config.get("neg_domains", []):
        terms = registry.get_with_domains("emotion.negative", [domain])
        lexicons["neg_terms"].update(terms)

    for domain in config.get("fight_domains", []):
        terms = registry.get_with_domains("tension.action_terms", [domain])
        lexicons["fight_terms"].update(terms)

    base_pos = registry.get("emotion.positive")
    base_neg = registry.get("emotion.negative")
    base_fight = registry.get("tension.action_terms")

    lexicons["pos_terms"].update(base_pos)
    lexicons["neg_terms"].update(base_neg)
    lexicons["fight_terms"].update(base_fight)

    return lexicons


def get_dynamic_lexicons_for_chunk(
    chunk_text: str,
    chunk_index: int,
    registry: LexiconRegistry | None = None,
) -> tuple[dict[str, set[str]], str]:
    """
    为单个 chunk 动态加载词表。

    Args:
        chunk_text: chunk 文本
        chunk_index: chunk 索引
        registry: 词表注册中心

    Returns:
        (词表集合, 检测到的类型)
    """
    if registry is None:
        registry = LexiconRegistry()
        registry.load()

    result = detect_genre(chunk_text, registry)
    lexicons = get_dynamic_lexicons(chunk_text, registry)

    return lexicons, result.genre


@dataclass
class WeightedGenreResult:
    """多类型加权检测结果"""

    genre_weights: list[tuple[str, float]]
    sample_count: int
    raw_scores: dict[str, float]


def detect_genre_weighted(
    chunk_texts: list[tuple[int, str]],
    sample_ratio: float = 0.1,
    min_samples: int = 10,
    registry: LexiconRegistry | None = None,
) -> WeightedGenreResult:
    """
    多类型加权检测：均匀采样 chunk，返回加权类型列表。

    策略:
      1. 均匀采样 sample_ratio 比例的 chunk（至少 min_samples）
      2. 对每个采样 chunk 检测类型
      3. 按置信度累加排序，取前 N 个直到权重和 ≥ 1.0
      4. 权重归一化

    Args:
        chunk_texts: chunk 列表，格式 [(chunk_id, text), ...]
        sample_ratio: 采样比例，默认 10%
        min_samples: 最少采样数，默认 10
        registry: 词表注册中心

    Returns:
        WeightedGenreResult: 包含加权类型列表、采样数、原始得分

    创建时间: 2026-04-06
    创建者: GLM-5
    任务: 多类型加权混合词表方案
    修改时间: 2026-04-06
    修改者: GLM-5
    修改内容: 移除 max_samples 限制，min_samples 提升到 10
    """
    if registry is None:
        registry = LexiconRegistry()
        registry.load()

    total_chunks = len(chunk_texts)
    if total_chunks == 0:
        return WeightedGenreResult(
            genre_weights=[("general", 1.0)],
            sample_count=0,
            raw_scores={},
        )

    target_samples = int(total_chunks * sample_ratio)
    sample_count = max(min_samples, min(target_samples, total_chunks))
    step = max(1, total_chunks // sample_count)
    sample_indices = list(range(0, total_chunks, step))[:sample_count]
    actual_sample_count = len(sample_indices)

    genre_scores: dict[str, float] = {}
    for idx in sample_indices:
        _, text = chunk_texts[idx]
        result = detect_genre(text, registry)
        for genre, score in result.scores.items():
            genre_scores[genre] = genre_scores.get(genre, 0.0) + score

    if not genre_scores:
        return WeightedGenreResult(
            genre_weights=[("general", 1.0)],
            sample_count=actual_sample_count,
            raw_scores={},
        )

    total_score = sum(genre_scores.values())
    if total_score == 0:
        return WeightedGenreResult(
            genre_weights=[("general", 1.0)],
            sample_count=actual_sample_count,
            raw_scores=genre_scores,
        )

    normalized_scores = {g: s / total_score for g, s in genre_scores.items()}

    sorted_genres = sorted(normalized_scores.items(), key=lambda x: -x[1])

    genre_weights: list[tuple[str, float]] = []
    accumulated = 0.0
    for genre, weight in sorted_genres:
        if accumulated >= 1.0:
            break
        genre_weights.append((genre, weight))
        accumulated += weight

    if genre_weights:
        total_weight = sum(w for _, w in genre_weights)
        genre_weights = [(g, w / total_weight) for g, w in genre_weights]

    if not genre_weights:
        genre_weights = [("general", 1.0)]

    return WeightedGenreResult(
        genre_weights=genre_weights,
        sample_count=actual_sample_count,
        raw_scores=normalized_scores,
    )


def get_weighted_lexicon_config(
    genre_weights: list[tuple[str, float]],
) -> list[tuple[str, dict[str, list[str]], float]]:
    """
    根据加权类型列表获取词表配置。

    Args:
        genre_weights: 类型权重列表，格式 [(genre, weight), ...]

    Returns:
        词表配置列表，格式 [(genre, lexicon_config, weight), ...]

    创建时间: 2026-04-06
    创建者: GLM-5
    任务: 多类型加权混合词表方案
    """
    result: list[tuple[str, dict[str, list[str]], float]] = []
    for genre, weight in genre_weights:
        config = get_recommended_lexicons(genre)
        result.append((genre, config, weight))
    return result


if __name__ == "__main__":
    from pathlib import Path

    novel_dir = Path("data/novel")
    novel_files = list(novel_dir.glob("*.txt"))

    print("=" * 60)
    print("小说类型自动检测（增强版）")
    print("=" * 60)

    for novel_file in novel_files[:2]:
        print(f"\n{'=' * 40}")
        print(f"文件: {novel_file.name}")
        print("=" * 40)

        result = detect_genre_from_file(novel_file, sample_size=5000)
        print("\n[整体检测]")
        print(f"  类型: {result.genre}")
        print(f"  置信度: {result.confidence:.2%}")
        print(f"  各类型得分: {result.scores}")
        if result.top_indicators:
            print(f"  关键指标: {result.top_indicators}")

        seq_result = detect_genre_sequence_from_file(novel_file, segment_size=5000, overlap=500)
        print(f"\n[分段检测] 共 {len(seq_result.segments)} 段")
        print(f"  类型分布: {seq_result.genre_distribution}")
        print(f"  主导类型: {seq_result.dominant_genre}")
        if seq_result.genre_transitions:
            print(f"  类型转变: {seq_result.genre_transitions}")
        else:
            print("  类型转变: 无")
