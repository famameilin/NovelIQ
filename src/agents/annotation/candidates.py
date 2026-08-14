"""
章节标注系统对话候选提取
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .schema import DialogueCandidate, DialogueParseStatus

_QUOTE_PAIRS = {
    "“": "”",
    "「": "」",
    "『": "』",
}
_DIALOGUE_LINE_PATTERN = re.compile(
    r"(?m)^(?P<prefix>[ \t]*(?:[-—]{1,2}|[^：:\n]{1,20}[：:])[ \t]*)(?P<content>[^\n]+)$"
)


@dataclass(frozen=True, slots=True)
class _CandidateSpan:
    """2026-08-07 用于在去重前保存候选原文区间"""

    start: int
    end: int
    content: str
    parse_status: DialogueParseStatus


def _candidate_key(chunk_id: int, span: _CandidateSpan) -> str:
    """2026-08-07 用于根据系统位置和原文生成稳定对话候选键"""
    digest = hashlib.sha256(
        f"{chunk_id}:{span.start}:{span.end}:{span.content}".encode()
    ).hexdigest()
    return f"dlg_{digest}"


def _extract_paired_quotes(text: str) -> list[_CandidateSpan]:
    """2026-08-07 用于扫描中文和 ASCII 成对引号候选"""
    spans: list[_CandidateSpan] = []
    stacks: dict[str, list[int]] = {opener: [] for opener in _QUOTE_PAIRS}
    ascii_start: int | None = None
    closer_to_opener = {closer: opener for opener, closer in _QUOTE_PAIRS.items()}

    for index, character in enumerate(text):
        if character in _QUOTE_PAIRS:
            stacks[character].append(index)
            continue
        opener = closer_to_opener.get(character)
        if opener is not None and stacks[opener]:
            open_index = stacks[opener].pop()
            content = text[open_index + 1 : index]
            if content.strip():
                spans.append(
                    _CandidateSpan(
                        start=open_index + 1,
                        end=index,
                        content=content,
                        parse_status="paired_quote",
                    )
                )
            continue
        if character != '"':
            continue
        if ascii_start is None:
            ascii_start = index
            continue
        content = text[ascii_start + 1 : index]
        if content.strip():
            spans.append(
                _CandidateSpan(
                    start=ascii_start + 1,
                    end=index,
                    content=content,
                    parse_status="paired_quote",
                )
            )
        ascii_start = None

    for _opener, starts in stacks.items():
        for open_index in starts:
            content = text[open_index + 1 :]
            if content.strip():
                spans.append(
                    _CandidateSpan(
                        start=open_index + 1,
                        end=len(text),
                        content=content,
                        parse_status="unclosed_quote",
                    )
                )
    if ascii_start is not None:
        content = text[ascii_start + 1 :]
        if content.strip():
            spans.append(
                _CandidateSpan(
                    start=ascii_start + 1,
                    end=len(text),
                    content=content,
                    parse_status="unclosed_quote",
                )
            )
    return spans


def _overlaps(start: int, end: int, spans: list[_CandidateSpan]) -> bool:
    """2026-08-07 用于避免对话行规则重复覆盖已有引号候选"""
    return any(start < span.end and end > span.start for span in spans)


def _extract_dialogue_lines(text: str, existing: list[_CandidateSpan]) -> list[_CandidateSpan]:
    """2026-08-07 用于提取破折号或人物冒号引出的潜在对话行"""
    spans: list[_CandidateSpan] = []
    for match in _DIALOGUE_LINE_PATTERN.finditer(text):
        content = match.group("content").strip()
        if not content:
            continue
        raw_start = match.start("content")
        leading = len(match.group("content")) - len(match.group("content").lstrip())
        start = raw_start + leading
        end = start + len(content)
        if _overlaps(start, end, [*existing, *spans]):
            continue
        spans.append(
            _CandidateSpan(
                start=start,
                end=end,
                content=content,
                parse_status="dialogue_line",
            )
        )
    return spans


def extract_dialogue_candidates(chunk_id: int, text: str) -> list[DialogueCandidate]:
    """2026-08-07 用于按原文顺序生成系统托管的完整对话候选"""
    quote_spans = _extract_paired_quotes(text)
    spans = [
        *quote_spans,
        *_extract_dialogue_lines(text, quote_spans),
    ]
    unique: dict[tuple[int, int, str], _CandidateSpan] = {}
    for span in spans:
        unique[(span.start, span.end, span.content)] = span
    return [
        DialogueCandidate(
            candidate_key=_candidate_key(chunk_id, span),
            chunk_id=chunk_id,
            start=span.start,
            end=span.end,
            content=span.content,
            parse_status=span.parse_status,
        )
        for span in sorted(unique.values(), key=lambda item: (item.start, item.end))
    ]


__all__ = ["extract_dialogue_candidates"]
