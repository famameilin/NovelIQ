from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from src.utils.text_utils import tokenize_words

_STOPWORDS: frozenset[str] = frozenset(
    {
        "之后",
        "时间",
        "起来",
        "这样",
        "这个",
        "那个",
        "如果",
        "但是",
        "因为",
        "所以",
        "没有",
        "时候",
        "可以",
        "不是",
        "然后",
        "自己",
        "他们",
        "我们",
        "已经",
        "只是",
        "一个",
        "这时",
        "此时",
        "却是",
    }
)

_STOPWORD_SUBSTRINGS: tuple[str, ...] = (
    "没有",
    "不是",
    "可以",
    "起来",
    "这个",
    "那个",
    "时候",
    "之后",
    "因为",
    "所以",
    "办法",
    "方法",
    "无法",
    "根本",
    "的",
    "境界",
    "联盟",
    "世界",
    "其他",
    "整个",
)

_COMBAT_STEMS: tuple[str, ...] = (
    "斩",
    "杀",
    "刺",
    "劈",
    "砍",
    "轰",
    "震",
    "破",
    "攻",
    "击",
    "挡",
    "闪",
    "避",
    "反击",
    "追击",
    "突袭",
    "格挡",
    "连击",
    "绝杀",
    "爆",
    "阵",
)

_SENSORY_STEMS: tuple[str, ...] = (
    "香",
    "臭",
    "腥",
    "甜",
    "苦",
    "酸",
    "辣",
    "咸",
    "麻",
    "烫",
    "冰",
    "冷",
    "热",
    "明",
    "暗",
    "亮",
    "昏",
    "朦",
    "耳",
    "响",
    "鸣",
    "轰",
    "刺",
)

_SEMANTIC_STEMS: tuple[str, ...] = (
    "宿命",
    "希望",
    "绝望",
    "信念",
    "责任",
    "荣耀",
    "屈辱",
    "欲望",
    "野心",
    "守护",
    "救赎",
    "背叛",
    "复仇",
    "牺牲",
    "抉择",
    "誓言",
    "信义",
    "义气",
    "仁义",
    "慈悲",
    "冷酷",
    "贪婪",
    "正义",
    "邪恶",
)

_TITLE_SUFFIXES: tuple[str, ...] = ("仙子", "魔女", "老祖", "真君", "尊者", "仙尊", "魔尊", "太子")
_PLACE_SUFFIXES: tuple[str, ...] = ("宗", "门", "派", "城", "山", "峰", "谷", "域", "宫", "殿", "阁", "楼", "塔")
_ARTIFACT_SUFFIXES: tuple[str, ...] = ("剑", "刀", "枪", "斧", "弓", "鞭", "戟", "印", "令", "珠", "鼎", "舟")
_TITLE_ONLY: frozenset[str] = frozenset(
    {
        "仙尊",
        "魔尊",
        "老祖",
        "仙子",
        "尊者",
        "真君",
        "城主",
        "宗主",
        "长老",
        "族长",
        "太子",
        "夫人",
        "先生",
        "大师",
        "圣子",
    }
)
_SENSORY_STOP: frozenset[str] = frozenset(
    {
        "明白",
        "明显",
        "影响",
        "麻烦",
        "冷笑",
        "苦笑",
        "暗道",
        "暗中",
        "暗自",
        "暗暗",
    }
)


def read_lexicon(path: Path) -> set[str]:
    items: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        items.add(value)
    return items


def write_lexicon(path: Path, items: Iterable[str]) -> None:
    path.write_text("\n".join(items) + "\n", encoding="utf-8")


def collect_tokens(texts: Iterable[str]) -> list[str]:
    tokens: list[str] = []
    for text in texts:
        tokens.extend(tokenize_words(text))
    return tokens


def collect_fallback_terms(texts: Iterable[str]) -> list[str]:
    terms: list[str] = []
    pattern = re.compile(r"[\u4e00-\u9fff]{2,4}")
    for text in texts:
        terms.extend(pattern.findall(text))
    return terms


def is_chinese_term(term: str) -> bool:
    return bool(re.fullmatch(r"[\u4e00-\u9fff]{2,6}", term))


def pick_candidates(
    freq: Counter[str],
    existing: set[str],
    predicate,
    limit: int,
    min_freq: int,
) -> list[str]:
    candidates: list[tuple[str, int]] = []
    for term, count in freq.items():
        if count < min_freq:
            continue
        if term in existing:
            continue
        term = term.strip().replace(" ", "").replace("\u3000", "")
        if not is_chinese_term(term):
            continue
        if term.startswith(("其他", "整个", "这个", "那个", "以及", "还有")):
            continue
        if predicate(term):
            candidates.append((term, count))
    candidates.sort(key=lambda item: (-item[1], item[0]))
    return [term for term, _ in candidates[:limit]]


def _collect_and_clean_tokens(
    texts: Iterable[str],
    stopwords: frozenset[str],
) -> tuple[list[str], str]:
    """
    收集文本token并清理，返回清理后的token列表和完整文本
    """
    tokens = collect_tokens(texts)
    if not tokens or sum(1 for token in tokens if len(token) <= 1) / max(len(tokens), 1) > 0.95:
        tokens = collect_fallback_terms(texts)
    tokens = [token.strip().replace(" ", "").replace("\u3000", "") for token in tokens if token.strip()]
    tokens = [token for token in tokens if token not in stopwords]
    full_text = "".join(texts)
    return tokens, full_text


def _extract_proper_nouns(
    freq: Counter[str],
    existing: set[str],
    stopword_substrings: tuple[str, ...],
    title_suffixes: tuple[str, ...],
    place_suffixes: tuple[str, ...],
    artifact_suffixes: tuple[str, ...],
    title_only: frozenset[str],
) -> list[str]:
    """
    从词频统计中提取专有名词候选词
    """

    def proper_noun_predicate(term: str) -> bool:
        if term.endswith(title_suffixes):
            return 2 <= len(term) <= 4
        if term.endswith(place_suffixes):
            return len(term) >= 3
        if term.endswith(artifact_suffixes):
            return len(term) >= 3
        return False

    candidates = pick_candidates(
        freq,
        existing,
        lambda term: (
            proper_noun_predicate(term)
            and term not in title_only
            and not any(sub in term for sub in stopword_substrings)
        ),
        limit=80,
        min_freq=2,
    )
    return list(dict.fromkeys(candidates))[:80]


def _extract_combat_terms(
    freq: Counter[str],
    existing: set[str],
    combat_stems: tuple[str, ...],
    stopword_substrings: tuple[str, ...],
) -> list[str]:
    """
    从词频统计中提取战斗术语候选词
    """
    return pick_candidates(
        freq,
        existing,
        lambda term: any(stem in term for stem in combat_stems) and not any(sub in term for sub in stopword_substrings),
        limit=40,
        min_freq=2,
    )


def _extract_sensory_terms(
    freq: Counter[str],
    existing: set[str],
    sensory_stems: tuple[str, ...],
    stopword_substrings: tuple[str, ...],
    sensory_stop: frozenset[str],
) -> list[str]:
    """
    从词频统计中提取感官术语候选词
    """
    return pick_candidates(
        freq,
        existing,
        lambda term: (
            any(stem in term for stem in sensory_stems)
            and term not in sensory_stop
            and 2 <= len(term) <= 4
            and not any(sub in term for sub in stopword_substrings)
        ),
        limit=30,
        min_freq=2,
    )


def _extract_semantic_terms(
    full_text: str,
    existing: set[str],
    semantic_stems: tuple[str, ...],
) -> list[str]:
    """
    从完整文本中提取语义术语
    """
    return [stem for stem in semantic_stems if stem in full_text and stem not in existing]


def expand_lexicons(texts: Iterable[str], lexicon_dir: Path) -> dict[str, list[str]]:
    """
    从文本中扩展词库，返回各类候选词
    """
    tokens, full_text = _collect_and_clean_tokens(texts, _STOPWORDS)
    freq = Counter(tokens)

    from .registry import LexiconRegistry

    reg = LexiconRegistry(base_dir=lexicon_dir)
    reg.load()

    lexicons = {
        "proper_nouns": set(reg.get("auxiliary.proper_nouns")),
        "combat": set(reg.get("tension.action_terms")),
        "sensory": set(reg.get("style.sensory_5sense")),
        "semantic_category": set(reg.get("style.semantic_10cat")),
    }
    additions: dict[str, list[str]] = {}
    additions["proper_nouns"] = _extract_proper_nouns(
        freq,
        lexicons["proper_nouns"],
        _STOPWORD_SUBSTRINGS,
        _TITLE_SUFFIXES,
        _PLACE_SUFFIXES,
        _ARTIFACT_SUFFIXES,
        _TITLE_ONLY,
    )
    additions["combat"] = _extract_combat_terms(
        freq,
        lexicons["combat"],
        _COMBAT_STEMS,
        _STOPWORD_SUBSTRINGS,
    )
    additions["sensory"] = _extract_sensory_terms(
        freq,
        lexicons["sensory"],
        _SENSORY_STEMS,
        _STOPWORD_SUBSTRINGS,
        _SENSORY_STOP,
    )
    additions["semantic_category"] = _extract_semantic_terms(
        full_text,
        lexicons["semantic_category"],
        _SEMANTIC_STEMS,
    )
    return additions


def apply_updates(additions: dict[str, list[str]], lexicon_dir: Path) -> None:
    for name, new_terms in additions.items():
        if not new_terms:
            continue
        path = lexicon_dir / f"{name}.txt"
        existing = read_lexicon(path)
        merged = list(existing) + new_terms
        write_lexicon(path, merged)


def update_lexicons_from_texts(texts: Iterable[str], lexicon_dir: Path, apply: bool = True) -> dict[str, list[str]]:
    additions = expand_lexicons(texts, lexicon_dir)
    if apply:
        apply_updates(additions, lexicon_dir)
    return additions
