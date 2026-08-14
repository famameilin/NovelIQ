"""
段落事实源存储与检索

paragraphs 是全文唯一的段落事实源（设计文档《章节粒度分析指标重设计》§5.1），
本仓储负责段落行的写入（先删后插）、完整性检查与按 run 读取。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from sqlalchemy import delete, exists, func, insert, or_, select
from sqlalchemy.engine import Row

from src.chunking.spans import ParagraphSpan
from src.config import settings
from src.storage.models import Chunk, Paragraph
from src.storage.repositories.base import BaseRepository


class ParagraphRepository(BaseRepository[Paragraph]):
    """
    段落事实源数据 Repository

    管理 run 内段落行的批量写入、查询与完整性判定，支持 run_id 过滤
    """

    def insert_paragraphs(self, run_id: str, spans: Sequence[ParagraphSpan]) -> int:
        """
        先删后插写入 run 的段落行（同 run 不可重跑前序阶段的语义）

        插入前校验段落身份、token 计数与坐标不变量，违反时抛 ValueError。
        content_hash 按 span.text 的 UTF-8 字节 sha256 计算；
        splitter_version/tokenizer_version 从 settings.paragraphs 读取，
        配置尚不存在时回退默认字符串 "1"。

        Returns:
            本次写入的段落行数
        """
        self._validate_spans(run_id, spans)

        paragraph_config = getattr(settings, "paragraphs", None)
        splitter_version = str(getattr(paragraph_config, "splitter_version", None) or "1")
        tokenizer_version = str(getattr(paragraph_config, "tokenizer_version", None) or "1")

        self.session.execute(delete(Paragraph).where(Paragraph.run_id == run_id))
        if not spans:
            return 0
        rows = [
            {
                "run_id": run_id,
                "paragraph_id": span.paragraph_id,
                "chunk_id": span.chunk_id,
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
                "content_hash": hashlib.sha256(span.text.encode("utf-8")).hexdigest(),
                "splitter_version": splitter_version,
                "tokenizer_version": tokenizer_version,
            }
            for span in spans
        ]
        self.session.execute(insert(Paragraph), rows)
        return len(rows)

    def _validate_spans(self, run_id: str, spans: Sequence[ParagraphSpan]) -> None:
        """2026-08-14 用于写入前校验段落身份、token 与坐标不变量"""
        for span in spans:
            if (
                span.paragraph_id is None
                or span.chunk_id is None
                or span.chapter_id is None
                or span.global_start_char is None
                or span.global_end_char is None
                or span.token_count is None
            ):
                raise ValueError(
                    "段落写入失败：段落身份字段（paragraph_id/chunk_id/chapter_id/"
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
            chunk_id = span.chunk_id
            if chunk_id is None:
                # 身份校验已拒绝 None，此处仅为类型收窄
                continue
            previous_end = last_local_end.get(chunk_id)
            if previous_end is not None and span.local_start_char < previous_end:
                raise ValueError(
                    "段落写入失败：同一 chunk 内 local 坐标必须严格单调不重叠，"
                    f"run_id={run_id} chunk_id={chunk_id} "
                    f"paragraph_id={span.paragraph_id} local_start_char={span.local_start_char} "
                    f"小于上一段落的 local_end_char={previous_end}"
                )
            last_local_end[chunk_id] = span.local_end_char

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

        offset_rows = self.session.execute(
            select(Chunk.chunk_id, Chunk.char_offset).where(
                Chunk.run_id == run_id, Chunk.char_offset.is_not(None)
            )
        ).all()
        char_offsets = {row.chunk_id: int(row.char_offset) for row in offset_rows}
        for span in spans:
            if span.chunk_id is None or span.global_start_char is None:
                # 身份校验已拒绝 None，此处仅为类型收窄
                continue
            chunk_offset = char_offsets.get(span.chunk_id)
            if chunk_offset is None:
                # chunks 行缺 char_offset 时无法校验，跳过该 chunk 的偏移一致性
                continue
            if span.global_start_char - chunk_offset != span.local_start_char:
                raise ValueError(
                    "段落写入失败：local 与 global 坐标偏移不一致，"
                    f"run_id={run_id} chunk_id={span.chunk_id} "
                    f"paragraph_id={span.paragraph_id} char_offset={chunk_offset} "
                    f"global_start_char={span.global_start_char} "
                    f"local_start_char={span.local_start_char}"
                )

    def has_paragraphs(self, run_id: str) -> bool:
        """run 是否存在段落行"""
        statement = select(Paragraph.paragraph_id).where(Paragraph.run_id == run_id).limit(1)
        return self.session.execute(statement).scalar_one_or_none() is not None

    def count_paragraphs(self, run_id: str) -> int:
        """统计指定 run 的段落行数"""
        statement = select(func.count()).select_from(Paragraph).where(Paragraph.run_id == run_id)
        return int(self.session.execute(statement).scalar_one() or 0)

    def fetch_paragraph_rows(self, run_id: str) -> Sequence[Row]:
        """
        读取 run 的全部段落行，按 paragraph_id 升序

        Returns:
            sqlalchemy.engine.Row 序列，支持字段名访问
        """
        statement = (
            select(
                Paragraph.paragraph_id,
                Paragraph.chunk_id,
                Paragraph.chapter_id,
                Paragraph.paragraph_index,
                Paragraph.source_paragraph_index,
                Paragraph.fragment_index,
                Paragraph.local_start_char,
                Paragraph.local_end_char,
                Paragraph.global_start_char,
                Paragraph.global_end_char,
                Paragraph.char_count,
                Paragraph.token_count,
                Paragraph.text,
                Paragraph.content_hash,
            )
            .where(Paragraph.run_id == run_id)
            .order_by(Paragraph.paragraph_id)
        )
        return self.session.execute(statement).all()

    def get_incomplete_paragraph_chunk_ids(self, run_id: str) -> list[int]:
        """
        找出段落数据不完整的 chunk：有正文但没有任何段落行、段落序号不连续
        （min != 0 或 count != max + 1）、或坐标为空的 chunk，返回排序后的 chunk_id 列表
        """
        paragraph_exists = exists().where(
            (Paragraph.run_id == Chunk.run_id) & (Paragraph.chunk_id == Chunk.chunk_id)
        )
        missing_statement = (
            select(Chunk.chunk_id)
            .where(Chunk.run_id == run_id)
            # 空文本 chunk 永远无法产出段落行，用 length(text) > 0 排除空串
            .where(func.length(Chunk.text) > 0)
            .where(~paragraph_exists)
        )
        missing_chunk_ids = {
            int(row.chunk_id)
            for row in self.session.execute(missing_statement).all()
        }
        count_label = func.count(Paragraph.paragraph_index)
        max_index_label = func.max(Paragraph.paragraph_index)
        min_index_label = func.min(Paragraph.paragraph_index)
        gapped_statement = (
            select(Paragraph.chunk_id)
            .where(Paragraph.run_id == run_id)
            .group_by(Paragraph.chunk_id)
            .having(or_(min_index_label != 0, count_label != max_index_label + 1))
        )
        gapped_chunk_ids = {
            int(row.chunk_id)
            for row in self.session.execute(gapped_statement).all()
        }
        null_statement = (
            select(Paragraph.chunk_id)
            .where(Paragraph.run_id == run_id)
            .where(
                or_(
                    Paragraph.local_start_char.is_(None),
                    Paragraph.local_end_char.is_(None),
                    Paragraph.global_start_char.is_(None),
                    Paragraph.global_end_char.is_(None),
                )
            )
            .group_by(Paragraph.chunk_id)
        )
        null_chunk_ids = {
            int(row.chunk_id)
            for row in self.session.execute(null_statement).all()
        }
        return sorted(missing_chunk_ids | gapped_chunk_ids | null_chunk_ids)
