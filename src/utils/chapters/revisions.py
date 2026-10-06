"""阶段三·后置：重复版本守卫

同一层级、同一编号、同一标题的相邻章节，且短章正文几乎完整出现在长章中时，
判定为作者的重复发布（早稿与扩写定稿共存于正文），仅保留正文更长的一版，
被弃版本与目录区一样不进入任何章节的正文区间。

三个条件缺一不可：真·不同内容的同号章文本包含率远低于阈值；正文短于下限的
不做内容比对（防止短文本字符级对齐的偶然高包含率）；非相邻的同号章不参与
判定（窄规则，避免跨章误伤）。
"""

from __future__ import annotations

import difflib

from loguru import logger

from src.utils.chapters.constants import ChapterConfig
from src.utils.chapters.models import ChapterData


def drop_duplicate_revisions(
    text: str,
    chapters: list[ChapterData],
    config: ChapterConfig | None = None,
) -> list[ChapterData]:
    """折叠相邻的同号同题重复版本；正文包含率低于阈值时全部保留"""
    config = config or ChapterConfig()
    result: list[ChapterData] = []
    index = 0
    while index < len(chapters):
        run_end = index + 1
        while run_end < len(chapters) and _same_revision_key(chapters[index], chapters[run_end]):
            run_end += 1
        result.extend(_collapse_run(text, chapters[index:run_end], config))
        index = run_end
    return result


def _same_revision_key(first: ChapterData, second: ChapterData) -> bool:
    """同层级 + 同编号 + 同标题（去空白）视为同一章的重复候选"""
    if first.number is None or first.level != second.level or first.number != second.number:
        return False
    return _normalize_title(first.display_title) == _normalize_title(second.display_title)


def _normalize_title(title: str) -> str:
    return "".join(title.split())


def _collapse_run(
    text: str,
    run: list[ChapterData],
    config: ChapterConfig,
) -> list[ChapterData]:
    """同键章节组内去重：以正文最长的成员为基准（等长取后者），包含率达标者判为重复"""
    if len(run) == 1:
        return run
    anchor_index = max(range(len(run)), key=lambda i: (_body_length(run[i]), i))
    anchor = run[anchor_index]
    kept: list[ChapterData] = []
    for member in run:
        if member is anchor:
            continue
        containment = _containment(text, member, anchor, config)
        if containment is None or containment < config.revision_containment_threshold:
            kept.append(member)
            continue
        logger.warning(
            "章节「{}」与「{}」同号同题且正文包含率 {:.0%}，判定为重复发布，仅保留「{}」",
            member.title,
            anchor.title,
            containment,
            anchor.title,
        )
    kept.append(anchor)
    kept.sort(key=lambda chapter: chapter.start_char)
    return kept


def _body_length(chapter: ChapterData) -> int:
    return chapter.end_char - chapter.start_char


def _containment(
    text: str,
    member: ChapterData,
    anchor: ChapterData,
    config: ChapterConfig,
) -> float | None:
    """短章正文被基准章正文按序吸收的比例；不满足比对前提时返回 None（保留）"""
    member_body = text[member.start_char : member.end_char]
    if _body_length(member) < config.revision_min_body_chars:
        return None
    matcher = difflib.SequenceMatcher(None, member_body, text[anchor.start_char : anchor.end_char], autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / len(member_body)
