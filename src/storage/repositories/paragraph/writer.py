"段落事实源写入（paragraphs 事实源，）"

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from src.storage.models import Chapter, Paragraph, ParagraphFeature, ParagraphMetric
from src.storage.records.inputs import ParagraphRecord as ParagraphSpan

#: 固定功能词计数列（20 列；文件词表命中即写，未命中为 0）
_FUNCTION_WORD_COLUMNS: dict[str, str] = {
    "之": "fw_之",
    "其": "fw_其",
    "者": "fw_者",
    "也": "fw_也",
    "所": "fw_所",
    "以": "fw_以",
    "而": "fw_而",
    "与": "fw_与",
    "则": "fw_则",
    "乃": "fw_乃",
    "于": "fw_于",
    "乎": "fw_乎",
    "矣": "fw_矣",
    "焉": "fw_焉",
    "哉": "fw_哉",
    "兮": "fw_兮",
    "尔": "fw_尔",
    "若": "fw_若",
    "为": "fw_为",
    "何": "fw_何",
}

#: 固定语义分类计数列（10 列；类别名来自 SEMANTIC_CATEGORY_MAPPING）
_SEMANTIC_CATEGORY_COLUMNS: dict[str, str] = {
    "combat": "semantic_combat",
    "body": "semantic_body",
    "relation": "semantic_relation",
    "faction": "semantic_faction",
    "command": "semantic_command",
    "action": "semantic_action",
    "psychology": "semantic_psychology",
    "measure": "semantic_measure",
    "emotion": "semantic_emotion",
    "color": "semantic_color",
}


def insert_paragraphs(session: Session, run_id: str, spans: Sequence[ParagraphSpan]) -> int:
    "先删后插写入 run 的段落行（同 run 不可重跑前序阶段的语义）"
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
            "text": span.text,
        }
        for span in spans
    ]
    session.execute(insert(Paragraph), rows)
    return len(rows)


def insert_paragraph_tension_observations(
    session: Session,
    run_id: str,
    rows: Sequence[tuple[int, float | None]],
) -> int:
    "先删后插写入 run 的段落表面张力 z（paragraph_features 的 tension_z 行）"
    session.execute(
        delete(ParagraphFeature).where(
            ParagraphFeature.run_id == run_id,
            ParagraphFeature.feature_code == "tension_z",
        )
    )
    materialized = [(int(paragraph_id), float(z)) for paragraph_id, z in rows if z is not None]
    if not materialized:
        return 0
    session.execute(
        insert(ParagraphFeature),
        [
            {
                "run_id": run_id,
                "paragraph_id": paragraph_id,
                "feature_code": "tension_z",
                "scalar_value": z,
            }
            for paragraph_id, z in materialized
        ],
    )
    return len(materialized)


def insert_paragraph_function_word_counts(
    session: Session,
    run_id: str,
    rows: Sequence[tuple[int, dict[str, int]]],
) -> int:
    "把 run 的功能词分类计数写进 paragraph_metrics 的 20 个 fw_* 明确列"
    updates = []
    for paragraph_id, counts in rows:
        values = {column: int((counts or {}).get(word, 0)) for word, column in _FUNCTION_WORD_COLUMNS.items()}
        updates.append({"b_run_id": run_id, "b_paragraph_id": int(paragraph_id), **values})
    if not updates:
        return 0
    session.execute(
        _update_metric_statement(_FUNCTION_WORD_COLUMNS.values()),
        updates,
        execution_options={"synchronize_session": False},
    )
    return len(updates)


def insert_paragraph_semantic_category_counts(
    session: Session,
    run_id: str,
    rows: Sequence[tuple[int, dict[str, int]]],
) -> int:
    "把 run 的语义类别计数写进 paragraph_metrics 的 10 个 semantic_* 明确列"
    updates = []
    for paragraph_id, counts in rows:
        values = {
            column: int((counts or {}).get(category, 0)) for category, column in _SEMANTIC_CATEGORY_COLUMNS.items()
        }
        updates.append({"b_run_id": run_id, "b_paragraph_id": int(paragraph_id), **values})
    if not updates:
        return 0
    session.execute(
        _update_metric_statement(_SEMANTIC_CATEGORY_COLUMNS.values()),
        updates,
        execution_options={"synchronize_session": False},
    )
    return len(updates)


def _update_metric_statement(columns):
    "按 (run_id, paragraph_id) 批量更新指标列（Core 表对象，绕开 ORM 拦截）"
    from typing import cast

    from sqlalchemy import bindparam
    from sqlalchemy.sql.schema import Table as SaTable

    metric_table = cast(SaTable, ParagraphMetric.__table__)
    return (
        update(metric_table)
        .where(
            metric_table.c.run_id == bindparam("b_run_id"),
            metric_table.c.paragraph_id == bindparam("b_paragraph_id"),
        )
        .values({column: bindparam(column) for column in columns})
    )


def validate_spans(session: Session, run_id: str, spans: Sequence[ParagraphSpan]) -> None:
    "用于写入前校验段落身份、token 与坐标不变量"
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
        if span.local_end_char - span.local_start_char != len(span.text):
            raise ValueError(
                "段落写入失败：local 坐标跨度必须等于原文字符数，"
                f"run_id={run_id} paragraph_id={span.paragraph_id} "
                f"local_start_char={span.local_start_char} local_end_char={span.local_end_char} "
                f"len(text)={len(span.text)}"
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

    # 正文起点事实源为 chapters.char_offset（正文与目录同键一对一）
    offset_rows = session.execute(select(Chapter.chapter_id, Chapter.char_offset).where(Chapter.run_id == run_id)).all()
    char_offsets = {int(row.chapter_id): int(row.char_offset) for row in offset_rows if row.char_offset is not None}
    for span in spans:
        if span.chapter_id is None or span.global_start_char is None:
            # 身份校验已拒绝 None，此处仅为类型收窄
            continue
        chapter_offset = char_offsets.get(span.chapter_id)
        if chapter_offset is None:
            # 章节无正文时无法校验 global 投影基准，跳过该章的偏移一致性
            continue
        if span.global_start_char - chapter_offset != span.local_start_char:
            raise ValueError(
                "段落写入失败：local 与 global 坐标偏移不一致，"
                f"run_id={run_id} chapter_id={span.chapter_id} "
                f"paragraph_id={span.paragraph_id} char_offset={chapter_offset} "
                f"global_start_char={span.global_start_char} "
                f"local_start_char={span.local_start_char}"
            )
