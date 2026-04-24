"""
Level3 描述性人物 mention 抽取。

创建时间: 2026-04-23
任务: level3-mention-retrieval
说明: 用保守规则抽取匿名/描述性人物指代，为 Level3 mention 级 query 提供结构化输入。
"""

from __future__ import annotations

import re

from src.rag.mention_extraction_types import PersonMention
from src.utils.text_utils import split_sentences

APPEARANCE_CUES = (
    "红衣",
    "白衣",
    "黑衣",
    "灰衣",
    "青衣",
    "紫衣",
    "黑袍",
    "灰袍",
    "白袍",
    "白发",
    "银发",
    "蒙面",
)
ACTION_CUES = (
    "出手",
    "持刀",
    "背剑",
    "提剑",
    "执剑",
    "负剑",
    "拔剑",
    "转身",
    "开口",
    "低声",
)
LOCATION_CUES = (
    "门口",
    "窗边",
    "屋内",
    "台上",
    "身旁",
    "院中",
)
ROLE_WORDS = (
    "女子",
    "少女",
    "姑娘",
    "妇人",
    "老者",
    "老人",
    "少年",
    "青年",
    "男子",
    "汉子",
    "侍卫",
    "掌柜",
    "公子",
    "书生",
    "和尚",
    "道士",
    "黑衣人",
    "灰衣人",
    "白衣人",
    "黑袍人",
    "灰袍人",
)

_ROLE_PATTERN = "|".join(sorted((re.escape(role) for role in ROLE_WORDS), key=len, reverse=True))
_FEATURE_PATTERN = "|".join(sorted((re.escape(cue) for cue in APPEARANCE_CUES + ACTION_CUES), key=len, reverse=True))
_BARE_COMPOUND_ROLE_PATTERN = "|".join(
    sorted(
        (re.escape(role) for role in ROLE_WORDS if any(cue in role for cue in APPEARANCE_CUES)),
        key=len,
        reverse=True,
    )
)
_DEMONSTRATIVE_PATTERN = r"(?:那个|那名|那位|这名|这位|那|这)"
_MENTION_PATTERNS = (
    re.compile(
        rf"{_DEMONSTRATIVE_PATTERN}?"
        rf"(?P<raw>(?:(?:穿着|穿|身着|披着)?(?:{_FEATURE_PATTERN})的?)+(?P<role>{_ROLE_PATTERN}))"
    ),
    re.compile(rf"(?P<raw>{_DEMONSTRATIVE_PATTERN}(?P<role>{_ROLE_PATTERN}))"),
    re.compile(rf"(?P<raw>(?:{'|'.join(LOCATION_CUES)})的(?P<role>{_ROLE_PATTERN}))"),
    re.compile(rf"(?P<raw>(?P<role>{_BARE_COMPOUND_ROLE_PATTERN}))"),
    re.compile(r"(?P<raw>掌柜的)"),
)


def _classify_mention(
    raw_text: str,
    appearance: list[str],
    actions: list[str],
    locations: list[str],
) -> str:
    """
    创建时间: 2026-04-23
    任务: level3-mention-retrieval
    说明: 根据抽到的线索给 mention 分桶，便于后续 rerank 和离线评测观察。

    修改时间: 2026-04-23
    任务: level3-mention-review-fix
    修改说明: 补充纯指代角色词与位置角色词分桶，避免“那个少女”一类泛 query 被误当成可用特征。
    """
    if actions and appearance:
        return "feature_action"
    if any(cue in raw_text for cue in APPEARANCE_CUES):
        return "appearance_based"
    if locations:
        return "location_role"
    if actions:
        return "action_role"
    if raw_text.startswith(("那个", "那名", "那位", "这名", "这位", "那", "这")):
        return "pronoun_role"
    return "role_based"


def _build_mention(raw_text: str, role_word: str, sentence_text: str) -> PersonMention:
    """
    创建时间: 2026-04-23
    任务: level3-mention-retrieval
    说明: 将正则命中的原文片段转换为 PersonMention，并抽取外貌/动作线索。

    修改时间: 2026-04-23
    任务: level3-mention-review-fix
    修改说明: 增补位置线索，并让纯指代角色词保留指示词以便正确分桶。
    """
    return _build_mention_from_cue_text(raw_text, role_word, sentence_text, raw_text)


def _build_mention_from_cue_text(
    raw_text: str,
    role_word: str,
    sentence_text: str,
    cue_text: str,
) -> PersonMention:
    """
    创建时间: 2026-04-24
    任务: fix-mention-local-cue-scope
    说明: 基于当前 mention 的局部文本抽取线索，避免同一句其他人物的动作被误绑到本 mention。
    """
    appearance = [cue for cue in APPEARANCE_CUES if cue in raw_text or cue in cue_text]
    actions = [cue for cue in ACTION_CUES if cue in raw_text or cue in cue_text]
    locations = [cue for cue in LOCATION_CUES if cue in raw_text]
    cues: dict[str, str | list[str]] = {
        "role_word": role_word,
        "appearance": appearance,
        "action": actions,
        "location": locations,
    }
    return PersonMention(
        raw_text=raw_text,
        mention_type=_classify_mention(raw_text, appearance, actions, locations),
        sentence_text=sentence_text,
        cues=cues,
        source="rule",
    )


def _build_mention_cue_text(sentence_text: str, start: int, end: int) -> str:
    """
    创建时间: 2026-04-24
    任务: fix-mention-local-cue-scope
    说明: 截取当前 mention 到下一个人物 mention 前的局部文本，作为动作/外貌线索扫描范围。
    """
    next_start: int | None = None
    for pattern in _MENTION_PATTERNS:
        for match in pattern.finditer(sentence_text, end):
            if match.start() < end:
                continue
            next_start = match.start() if next_start is None else min(next_start, match.start())
            break
    return sentence_text[start : next_start if next_start is not None else len(sentence_text)]


def _spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    """
    创建时间: 2026-04-24
    任务: fix-bare-compound-mention-extraction
    说明: 判断两个 mention 命中范围是否重叠，用于保留更完整的上游命中，避免“那个灰衣人/灰衣人”重复出证。
    """
    return left[0] < right[1] and right[0] < left[1]


def extract_person_mentions(text: str) -> list[PersonMention]:
    """
    创建时间: 2026-04-23
    任务: level3-mention-retrieval
    说明: 从文本中保守抽取描述性人物 mention；规则宁窄勿宽，避免高频上游噪声。

    修改时间: 2026-04-24
    任务: fix-mention-local-cue-scope
    修改说明: 每个 mention 只从局部 cue_text 抽动作/外貌线索，避免多人物共句时互相污染。

    修改时间: 2026-04-24
    任务: fix-bare-compound-mention-extraction
    修改说明: 增补“灰衣人/黑衣人”等裸露复合角色词的窄规则，并用 span overlap 避免重复抽取子串。
    """
    mentions: list[PersonMention] = []
    seen: set[tuple[str, str]] = set()

    for sentence in split_sentences(text):
        sentence_text = sentence.strip()
        if not sentence_text:
            continue
        matched_spans: list[tuple[int, int]] = []
        for pattern in _MENTION_PATTERNS:
            for match in pattern.finditer(sentence_text):
                raw_text = match.group("raw").strip()
                if not raw_text:
                    continue
                current_span = (match.start(), match.end())
                if any(_spans_overlap(current_span, existing_span) for existing_span in matched_spans):
                    continue
                role_word = match.groupdict().get("role") or raw_text
                key = (raw_text, sentence_text)
                if key in seen:
                    continue
                seen.add(key)
                matched_spans.append(current_span)
                cue_text = _build_mention_cue_text(sentence_text, match.start(), match.end())
                mentions.append(_build_mention_from_cue_text(raw_text, role_word, sentence_text, cue_text))

    return mentions
