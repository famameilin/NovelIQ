"""
语言风格指标计算模块 (扩展)

创建时间: 2026-03-13
创建者: TraeAI
任务: refactor-metrics-layer-functions
说明: 从 style_metrics.py 提取扩展指标计算函数

修改时间: 2026-03-25
修改者: TraeAI
任务: fix-category-density-keys
修改内容: 删除硬编码 SEMANTIC_CATEGORIES，改为从词表文件加载
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from pathlib import Path

import jieba

from src.config.constants import CLASSICAL_PATTERNS

from .lexicon_metrics import count_mixed_hits
from .text_utils import tokenize_words

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

CLASSICAL_IMAGERY: set[str] = set()


def _load_classical_imagery() -> set[str]:
    global CLASSICAL_IMAGERY
    if CLASSICAL_IMAGERY:
        return CLASSICAL_IMAGERY

    try:
        from src.lexicons.registry import LexiconRegistry

        reg = LexiconRegistry()
        chars = reg.get("culture.classical_imagery")
        CLASSICAL_IMAGERY = set(chars)
    except FileNotFoundError:
        CLASSICAL_IMAGERY = {
            "月",
            "风",
            "花",
            "雪",
            "云",
            "雨",
            "山",
            "水",
            "江",
            "河",
            "松",
            "竹",
            "梅",
            "兰",
            "菊",
            "柳",
            "桃",
            "杏",
            "荷",
            "莲",
            "鹤",
            "雁",
            "燕",
            "莺",
            "蝶",
            "蝉",
            "萤",
            "鱼",
            "龙",
            "凤",
            "楼",
            "阁",
            "亭",
            "台",
            "桥",
            "舟",
            "帆",
            "灯",
            "烛",
            "香",
            "琴",
            "棋",
            "书",
            "画",
            "剑",
            "酒",
            "茶",
            "梦",
            "魂",
            "影",
        }
    return CLASSICAL_IMAGERY


IDIOM_SET: set[str] = set()


def _load_idiom_set() -> set[str]:
    global IDIOM_SET
    if IDIOM_SET:
        return IDIOM_SET

    try:
        from src.lexicons.registry import LexiconRegistry

        reg = LexiconRegistry()
        idioms = reg.get("culture.idioms")
        IDIOM_SET = set(idioms)
    except FileNotFoundError:
        IDIOM_SET = {
            "一帆风顺",
            "一鸣惊人",
            "一诺千金",
            "一举两得",
            "一马当先",
            "三心二意",
            "四面楚歌",
            "五光十色",
            "六神无主",
            "七上八下",
            "八仙过海",
            "九牛一毛",
            "十全十美",
            "百发百中",
            "千方百计",
            "万紫千红",
            "心旷神怡",
            "兴高采烈",
            "喜出望外",
            "眉开眼笑",
            "愁眉苦脸",
            "垂头丧气",
            "怒发冲冠",
            "惊慌失措",
            "忐忑不安",
            "心平气和",
            "从容不迫",
            "悠然自得",
            "怡然自乐",
            "泰然处之",
            "井井有条",
            "有条不紊",
            "一丝不苟",
            "精益求精",
            "尽善尽美",
            "画龙点睛",
            "锦上添花",
            "雪中送炭",
            "如虎添翼",
            "画蛇添足",
            "守株待兔",
            "刻舟求剑",
            "掩耳盗铃",
            "自相矛盾",
            "亡羊补牢",
            "叶公好龙",
            "杯弓蛇影",
            "狐假虎威",
            "井底之蛙",
            "对牛弹琴",
        }

    return IDIOM_SET


def compute_idiom_density(
    texts: list[str],
) -> float:
    if not texts:
        return 0.0

    idioms = _load_idiom_set()

    all_words: list[str] = []
    idiom_count = 0

    for text in texts:
        words = list(jieba.cut(text))
        all_words.extend(words)
        for word in words:
            if word in idioms:
                idiom_count += 1

    total_words = len(all_words)
    if total_words == 0:
        return 0.0

    return idiom_count / total_words


def compute_classical_sentence_ratio(
    texts: list[str],
) -> float:
    if not texts:
        return 0.0

    classical_count = 0
    total_sentences = 0

    for text in texts:
        sentences = re.split(r"[。！？\n]", text)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 4:
                continue
            total_sentences += 1
            for pattern in CLASSICAL_PATTERNS:
                if re.search(pattern, sentence):
                    classical_count += 1
                    break

    return classical_count / total_sentences if total_sentences > 0 else 0.0


def compute_vocab_breadth(
    all_tokens: list[str],
) -> float:
    if not all_tokens:
        return 0.0

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
) -> float:
    if not texts:
        return 0.0

    all_sentences = []
    for text in texts:
        sentences = re.split(r"[。！？\n]", text)
        for sent in sentences:
            sent = sent.strip()
            if sent:
                all_sentences.append(sent)

    if len(all_sentences) < 2:
        return 0.0

    sent_lengths = [len(sent) for sent in all_sentences]

    return statistics.stdev(sent_lengths)


def compute_function_word_vector(
    texts: list[str],
) -> dict[str, float]:
    if not texts:
        return dict.fromkeys(FUNCTION_WORDS, 0.0)

    total_chars = sum(len(text) for text in texts)
    if total_chars == 0:
        return dict.fromkeys(FUNCTION_WORDS, 0.0)

    all_chars = []
    for text in texts:
        all_chars.extend([c for c in text if c in FUNCTION_WORDS])

    counts = Counter(all_chars)

    return {word: counts.get(word, 0) / total_chars for word in FUNCTION_WORDS}


def _load_semantic_categories() -> dict[str, list[str]]:
    """
    加载语义类别词表

    修改时间: 2026-03-25
    修改者: TraeAI
    任务: fix-category-density-keys
    修改内容: 新增函数，从词表文件加载分类
    """
    from src.metrics.style_metrics import parse_semantic_category_lexicon

    lexicon_path = Path(__file__).parent.parent.parent / "data" / "lexicons" / "semantic_category.txt"

    if not lexicon_path.exists():
        return {key: [] for key in SEMANTIC_CATEGORY_KEYS}

    parsed_categories = parse_semantic_category_lexicon(str(lexicon_path))
    return {key: parsed_categories.get(key, []) for key in SEMANTIC_CATEGORY_KEYS}


def compute_category_density(
    texts: list[str],
) -> dict[str, float]:
    """
    计算语义类别密度

    修改时间: 2026-03-25
    修改者: TraeAI
    任务: fix-category-density-keys
    修改内容: 从词表文件加载分类，使用英文键名
    """
    category_terms = _load_semantic_categories()

    if not texts:
        return dict.fromkeys(category_terms.keys(), 0.0)

    total_tokens = 0
    category_hits = dict.fromkeys(category_terms.keys(), 0)

    for text in texts:
        if not text:
            continue

        tokens = tokenize_words(text)
        total_tokens += len(tokens)

        if not tokens:
            continue

        for category, terms in category_terms.items():
            if not terms:
                continue
            category_hits[category] += count_mixed_hits(text, tokens, terms)

    if total_tokens == 0:
        return dict.fromkeys(category_terms.keys(), 0.0)

    result = {}
    for category, hit_count in category_hits.items():
        result[category] = min(hit_count / total_tokens, 1.0)

    return result


def compute_imagery_density(
    texts: list[str],
) -> float:
    if not texts:
        return 0.0

    total_chars = sum(len(text) for text in texts)
    if total_chars == 0:
        return 0.0

    imagery_set = _load_classical_imagery()
    all_chars = []
    for text in texts:
        all_chars.extend([c for c in text if c in imagery_set])

    return len(all_chars) / total_chars
