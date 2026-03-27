"""消歧证据画像工具。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

EVIDENCE_STRENGTH_WEAK = "weak"
EVIDENCE_STRENGTH_MIXED = "mixed"
EVIDENCE_STRENGTH_STRONG = "strong"

EVIDENCE_SIGNAL_UNIQUE_BODY_MARKER = "unique_body_marker"
EVIDENCE_SIGNAL_NAMING_SCENE = "naming_scene"
EVIDENCE_SIGNAL_KINSHIP_IDENTITY = "kinship_identity"
EVIDENCE_SIGNAL_IDENTITY_REVEAL = "identity_reveal"
EVIDENCE_SIGNAL_STABLE_TITLE = "stable_title_or_rank"
EVIDENCE_SIGNAL_APPEARANCE_ONLY = "appearance_only"

_SUMMARY_MARKER = "【前文总结】"
_IDENTITY_MARKERS = (
    "【自报身份】",
    "【身份提示】",
    "【被点名】",
    "【外貌描述】",
    "【独特标记】",
    "【亲缘身份】",
    "【命名场景】",
)
_BODY_MARKER_KEYWORDS = (
    "胎记",
    "纹身",
    "印记",
    "符号",
    "伤疤",
    "伤痕",
    "掌纹",
    "瞳色",
    "脊椎处",
    "眉心",
    "额间",
    "白金火焰",
)
_NAMING_KEYWORDS = ("取名", "起名", "命名", "名为", "叫作", "就叫", "小名")
_KINSHIP_KEYWORDS = ("之子", "儿子", "女儿", "父亲", "母亲", "其子", "所生", "亲生", "嫡子", "嫡女")
_IDENTITY_REVEAL_KEYWORDS = ("真实身份", "其实就是", "竟是", "原来是", "真容", "原形")
_TITLE_KEYWORDS = ("少爷", "小姐", "公子", "侯爷", "殿下", "掌门", "宗主", "圣女")
_APPEARANCE_ONLY_PATTERN = re.compile(r"(灰衣人|白发少女|黑衣人|青衣人|少年|少女|男子|女子|婴儿|婴孩)")


@dataclass(frozen=True)
class EvidenceProfile:
    """候选称呼的程序化证据画像。"""

    has_original_sentence: bool = False
    has_identity_clue: bool = False
    has_summary: bool = False
    strong_signals: list[str] = field(default_factory=list)
    strength: str = EVIDENCE_STRENGTH_WEAK


def _split_context_segments(context: str) -> list[str]:
    if not context:
        return []
    segments: list[str] = []
    remaining = context.strip()
    if remaining.startswith(_SUMMARY_MARKER):
        head, separator, tail = remaining.partition("\n")
        if head:
            segments.append(head)
        if separator:
            remaining = tail
        else:
            trailing_segments = [segment.strip() for segment in remaining.split(" | ") if segment.strip()]
            if len(trailing_segments) > 1:
                return trailing_segments
            remaining = ""
    if remaining:
        for segment in remaining.split(" | "):
            normalized = segment.strip()
            if normalized:
                segments.append(normalized)
    return segments


def _classify_signal(segment: str) -> str | None:
    if any(keyword in segment for keyword in _BODY_MARKER_KEYWORDS):
        return EVIDENCE_SIGNAL_UNIQUE_BODY_MARKER
    if any(keyword in segment for keyword in _NAMING_KEYWORDS):
        return EVIDENCE_SIGNAL_NAMING_SCENE
    if any(keyword in segment for keyword in _KINSHIP_KEYWORDS):
        return EVIDENCE_SIGNAL_KINSHIP_IDENTITY
    if any(keyword in segment for keyword in _IDENTITY_REVEAL_KEYWORDS):
        return EVIDENCE_SIGNAL_IDENTITY_REVEAL
    if any(keyword in segment for keyword in _TITLE_KEYWORDS):
        return EVIDENCE_SIGNAL_STABLE_TITLE
    if _APPEARANCE_ONLY_PATTERN.search(segment):
        return EVIDENCE_SIGNAL_APPEARANCE_ONLY
    return None


def build_evidence_profile(context: str) -> EvidenceProfile:
    """根据上下文构建证据画像。"""

    has_original_sentence = False
    has_identity_clue = False
    has_summary = False
    strong_signals: list[str] = []

    for segment in _split_context_segments(context):
        if segment.startswith(_SUMMARY_MARKER):
            has_summary = True
            continue

        if segment.startswith(_IDENTITY_MARKERS):
            has_identity_clue = True
            signal = _classify_signal(segment)
            if signal and signal not in strong_signals:
                strong_signals.append(signal)
            continue

        has_original_sentence = True
        signal = _classify_signal(segment)
        if signal and signal not in strong_signals:
            strong_signals.append(signal)

    if any(
        signal in strong_signals
        for signal in (
            EVIDENCE_SIGNAL_UNIQUE_BODY_MARKER,
            EVIDENCE_SIGNAL_NAMING_SCENE,
            EVIDENCE_SIGNAL_KINSHIP_IDENTITY,
            EVIDENCE_SIGNAL_IDENTITY_REVEAL,
            EVIDENCE_SIGNAL_STABLE_TITLE,
        )
    ):
        strength = EVIDENCE_STRENGTH_STRONG
    elif has_original_sentence or has_identity_clue:
        strength = EVIDENCE_STRENGTH_MIXED
    elif has_summary:
        strength = EVIDENCE_STRENGTH_WEAK
    else:
        strength = EVIDENCE_STRENGTH_WEAK

    return EvidenceProfile(
        has_original_sentence=has_original_sentence,
        has_identity_clue=has_identity_clue,
        has_summary=has_summary,
        strong_signals=strong_signals,
        strength=strength,
    )


def format_evidence_profile(profile: EvidenceProfile) -> str:
    """将证据画像格式化为 prompt 可读文本。"""

    signal_text = "、".join(profile.strong_signals) if profile.strong_signals else "无"
    return (
        "【证据画像："
        f"原文例句={'是' if profile.has_original_sentence else '否'}；"
        f"身份线索={'是' if profile.has_identity_clue else '否'}；"
        f"前文摘要={'是' if profile.has_summary else '否'}；"
        f"强信号={signal_text}；"
        f"证据强度={profile.strength}"
        "】"
    )
