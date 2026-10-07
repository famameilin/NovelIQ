"""
段落事实源写入（paragraphs 事实源，§5.1）

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分——从 paragraph_repository.py 提取段落行写入逻辑
说明: 纯结构搬移，不改 SQL 与校验行为。insert_paragraphs 先删后插写入
run 的段落行（同 run 不可重跑前序阶段的语义），插入前经 validate_spans
校验段落身份、token 计数与 local/global 坐标不变量，违反时抛 ValueError。
ParagraphRepository（paragraph_repository.py）保留同名门面方法委托至此。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from src.storage.input_records import ParagraphRecord as ParagraphSpan
from src.storage.models import Chapter, Paragraph


def insert_paragraphs(session: Session, run_id: str, spans: Sequence[ParagraphSpan]) -> int:
    """
    先删后插写入 run 的段落行（同 run 不可重跑前序阶段的语义）

    插入前校验段落身份、token 计数与坐标不变量，违反时抛 ValueError。

    Returns:
        本次写入的段落行数
    """
    validate_spans(session, run_id, spans)

    session.execute(delete(Paragraph).where(Paragraph.run_id == run_id))
    if not spans:
        return 0
    rows = [
        {
            "run_id": run_id,
            "paragraph_id": span.paragraph_id,
            "chapter_id": span.chapter_id,
            "paragraph_index": span.paragraph_index,
            "source_paragraph_index": span.source_paragraph_index,
            "fragment_index": span.fragment_index,
            "local_start_char": span.local_start_char,
            "local_end_char": span.local_end_char,
            "global_start_char": span.global_start_char,
            "global_end_char": span.global_end_char,
            "char_count": span.char_count,
            "token_count": span.token_count,
            "text": span.text,
        }
        for span in spans
    ]
    session.execute(insert(Paragraph), rows)
    return len(rows)


def validate_spans(session: Session, run_id: str, spans: Sequence[ParagraphSpan]) -> None:
    """2026-08-14 用于写入前校验段落身份、token 与坐标不变量"""
    for span in spans:
        if (
            span.paragraph_id is None
            or span.chapter_id is None
            or span.global_start_char is None
            or span.global_end_char is None
            or span.token_count is None
        ):
            raise ValueError(
                "段落写入失败：段落身份字段（paragraph_id/chapter_id/"
                f"global_start_char/global_end_char/token_count）不得为 None，"
                f"run_id={run_id} paragraph_index={span.paragraph_index}"
            )
        if span.token_count < 0:
            raise ValueError(
                f"段落写入失败：token_count 不得为负数，run_id={run_id} "
                f"paragraph_id={span.paragraph_id} token_count={span.token_count}"
            )

    last_local_end: dict[int, int] = {}
    for span in spans:
        chapter_id = span.chapter_id
        if chapter_id is None:
            # 身份校验已拒绝 None，此处仅为类型收窄
            continue
        previous_end = last_local_end.get(chapter_id)
        if previous_end is not None and span.local_start_char < previous_end:
            raise ValueError(
                "段落写入失败：同一章节内 local 坐标必须严格单调不重叠，"
                f"run_id={run_id} chapter_id={chapter_id} "
                f"paragraph_id={span.paragraph_id} local_start_char={span.local_start_char} "
                f"小于上一段落的 local_end_char={previous_end}"
            )
        last_local_end[chapter_id] = span.local_end_char

    previous_global_end = 0
    for span in spans:
        if span.global_start_char is None or span.global_end_char is None:
            # 身份校验已拒绝 None，此处仅为类型收窄
            continue
        if span.global_start_char < previous_global_end:
            raise ValueError(
                "段落写入失败：全文 global 坐标必须严格单调不重叠，"
                f"run_id={run_id} paragraph_id={span.paragraph_id} "
                f"global_start_char={span.global_start_char} 小于上一段落的 "
                f"global_end_char={previous_global_end}"
            )
        previous_global_end = span.global_end_char

    offset_rows = session.execute(
        select(Chapter.chapter_id, Chapter.char_offset).where(
            Chapter.run_id == run_id, Chapter.char_offset.is_not(None)
        )
    ).all()
    char_offsets = {row.chapter_id: int(row.char_offset) for row in offset_rows}
    for span in spans:
        if span.chapter_id is None or span.global_start_char is None:
            # 身份校验已拒绝 None，此处仅为类型收窄
            continue
        chapter_offset = char_offsets.get(span.chapter_id)
        if chapter_offset is None:
            # chapters 行缺 char_offset 时无法校验，跳过该章的偏移一致性
            continue
        if span.global_start_char - chapter_offset != span.local_start_char:
            raise ValueError(
                "段落写入失败：local 与 global 坐标偏移不一致，"
                f"run_id={run_id} chapter_id={span.chapter_id} "
                f"paragraph_id={span.paragraph_id} char_offset={chapter_offset} "
                f"global_start_char={span.global_start_char} "
                f"local_start_char={span.local_start_char}"
            )
