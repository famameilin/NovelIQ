"""目录（TOC）页识别

网文 txt 有时在正文开头带一页目录（「目录」标题 + 章节标题列表），
目录行若直接参与章节候选收集会造成误切。本模块识别文件开头 10% 内的
目录页，返回待跳过的字符范围；识别失败返回 None（不跳过任何内容）。
"""

from __future__ import annotations

import re

from src.chapters.constants import _CN_NUMERALS_CLASS, ChapterConfig

_TOC_TITLE_RE = re.compile(r"^[ \t]*目[ \t]*录[ \t]*[:：]?[ \t]*$")
# 目录条目：与章节标题格式相近的行（第一章 XXX / 第1章 XXX / 卷一 等）
_TOC_ENTRY_RE = re.compile(
    rf"^[ \t]*第?{_CN_NUMERALS_CLASS}+[章节回卷篇][ \t]*.*$",
)


def detect_toc_range(text: str, config: ChapterConfig | None = None) -> tuple[int, int] | None:
    """返回目录页字符范围 [start, end)（end 为目录最后一条之后的正文起点），未识别返回 None"""
    config = config or ChapterConfig()
    if not config.toc_enabled or not text:
        return None

    max_pos = int(len(text) * config.toc_max_ratio)
    toc_start: int | None = None
    entry_count = 0
    seen_entries: set[str] = set()
    pos = 0

    for line in text.splitlines():
        line_start = pos
        pos += len(line) + 1
        if toc_start is None:
            if line_start >= max_pos:
                break
            if not line.strip():
                continue
            if _TOC_TITLE_RE.match(line):
                toc_start = line_start
            continue
        # 目录条目连续排布，遇到空行或非条目行即认为目录页结束，
        # 避免与正文中格式相同的真实章节标题混淆
        if not line.strip():
            if entry_count >= config.toc_min_entries:
                return (toc_start, line_start)
            return None
        if _TOC_ENTRY_RE.match(line):
            # 目录条目通常不重复；若出现与已收集条目同名的行（忽略行尾页码），
            # 说明已进入正文（正文首个真实标题与目录首条同名），提前结束目录页，
            # 避免吞掉正文真实章节标题
            normalized_line = re.sub(r"[ \t]*\d+[ \t]*$", "", line)
            if normalized_line in seen_entries:
                if entry_count >= config.toc_min_entries:
                    return (toc_start, line_start)
                return None
            seen_entries.add(normalized_line)
            entry_count += 1
            continue
        if entry_count >= config.toc_min_entries:
            return (toc_start, line_start)
        return None

    if toc_start is not None and entry_count >= config.toc_min_entries:
        return (toc_start, len(text))
    return None
