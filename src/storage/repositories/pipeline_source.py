"""按原文快照创建可恢复的独立章节工作"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.agents.annotation.identity import stable_digest, text_digest
from src.storage.models import Chapter, ChapterAnnotationRecord, Paragraph, SourceManifest
from src.storage.repositories.pipeline_work import ImmutableWorkConflict, WorkReceipt


def verify_source_manifest(session: Session, run_id: str) -> str:
    """未来正文也属于正式输入，释放前必须核对全书而不是仅核对被引用段落"""
    hashes = set(session.execute(select(ChapterAnnotationRecord.source_manifest_hash).where(
        ChapterAnnotationRecord.run_id == run_id,
    )).scalars())
    if len(hashes) != 1 or None in hashes:
        raise ImmutableWorkConflict("正式结果没有唯一的全书原文快照，请重新分析")
    source_hash = str(hashes.pop())
    source = session.get(SourceManifest, source_hash)
    if source is None or source.run_id != run_id:
        raise ImmutableWorkConflict("正式原文快照不存在")
    chapters = session.execute(select(Chapter).where(
        Chapter.run_id == run_id, Chapter.text.isnot(None),
    ).with_for_update(read=True)).scalars()
    paragraphs = session.execute(select(Paragraph).where(
        Paragraph.run_id == run_id,
    ).with_for_update(read=True)).scalars()
    chapter_hashes = {str(row.chapter_id): text_digest(row.text) for row in chapters if row.text is not None}
    if (chapter_hashes != source.chapter_hashes
            or {str(row.paragraph_id): text_digest(row.text) for row in paragraphs} != source.paragraph_hashes):
        raise ImmutableWorkConflict("全书正文在正式输入冻结后发生变化，请创建新的分析 run")
    return source_hash


def freeze_formal_source(session_factory: Callable[[], Session], run_id: str) -> list[dict[str, Any]]:
    """冻结全书原文并构造章节输入，不领取或发布工作"""
    with session_factory() as session, session.begin():
        chapters = list(session.execute(select(Chapter).where(
            Chapter.run_id == run_id, Chapter.text.isnot(None),
        ).order_by(Chapter.sequence, Chapter.chapter_id)).scalars())
        paragraphs = list(session.execute(select(Paragraph).where(Paragraph.run_id == run_id)
                         .order_by(Paragraph.chapter_id, Paragraph.paragraph_index)).scalars())
        paragraph_groups: dict[int, list[Paragraph]] = defaultdict(list)
        for row in paragraphs:
            paragraph_groups[row.chapter_id].append(row)
        chapter_hashes = {str(row.chapter_id): text_digest(row.text) for row in chapters if row.text is not None}
        paragraph_hashes = {str(row.paragraph_id): text_digest(row.text) for row in paragraphs}
        source_hash = stable_digest(run_id, chapter_hashes, paragraph_hashes)
        session.execute(insert(SourceManifest).values(
            source_manifest_hash=source_hash, run_id=run_id,
            chapter_hashes=chapter_hashes, paragraph_hashes=paragraph_hashes,
        ).on_conflict_do_nothing(index_elements=[SourceManifest.source_manifest_hash]))
        prior = list(session.execute(select(ChapterAnnotationRecord).where(
            ChapterAnnotationRecord.run_id == run_id,
        )).scalars())
        if any(row.source_manifest_hash != source_hash for row in prior):
            raise ImmutableWorkConflict("当前 run 的标注不属于本次原文快照，请创建新分析 run")
        work: list[dict[str, Any]] = []
        for chapter in chapters:
            chapter_paragraphs = paragraph_groups[chapter.chapter_id]
            if not chapter_paragraphs:
                raise ValueError(f"章节缺少段落事实源: chapter_id={chapter.chapter_id}")
            work.append({
                "chapter_id": chapter.chapter_id,
                "chapter_sequence": chapter.sequence,
                "chapter_label": chapter.display_index_label or f"第{chapter.sequence}章",
                "source_manifest_hash": source_hash,
                "chapter_text_hash": chapter_hashes[str(chapter.chapter_id)],
                "paragraph_manifest_hash": stable_digest([
                    (row.paragraph_id, row.local_start_char, row.local_end_char, text_digest(row.text))
                    for row in chapter_paragraphs
                ]),
            })
    return work


def formal_receipt(run_id: str, payload: dict[str, Any]) -> WorkReceipt:
    """按 enqueue 时代的同一公式铸造 work_id，保证与存量正式结果的 formal_work_id 兼容"""
    return WorkReceipt(
        work_id=stable_digest(
            run_id, "formal_current", f"chapter:{payload['chapter_id']}",
            stable_digest(payload), payload["source_manifest_hash"],
        ),
        run_id=run_id,
        work_kind="formal_current",
        payload=dict(payload),
        cutoff_hash=payload["source_manifest_hash"],
        attempt_epoch=0,
    )


def formal_committed_chapter_ids(session_factory: Callable[[], Session], run_id: str) -> set[int]:
    """章节状态即工作状态：有正式标注的章节就是已完成工作"""
    with session_factory() as session:
        return set(session.execute(select(ChapterAnnotationRecord.chapter_id).where(
            ChapterAnnotationRecord.run_id == run_id,
        )).scalars())


def prepare_formal_work(session_factory: Callable[[], Session], run_id: str) -> list[WorkReceipt]:
    """按全书快照构造章节序的工作回执；重启恢复 = 重查后过滤已提交章节"""
    work = freeze_formal_source(session_factory, run_id)
    return [formal_receipt(run_id, payload) for payload in work]


