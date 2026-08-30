"""
段落事实源存储与检索

paragraphs 是全文唯一的段落事实源（设计文档《章节粒度分析指标重设计》§5.1），
本仓储负责段落行的写入（先删后插）、完整性检查与按 run 读取，
并管理段落级派生数据表：paragraph_metrics（原始计数与充分统计量，§5.3）、
paragraph_topics（段落 LDA 主题，§5.4）与 paragraph_curves（段落曲线，§5.5）。

主题链路按《分析能力扩展路线图》§5.8-5.10：topic_model_runs 保存模型契约、
paragraph_topic_inference 每段一行保存推断状态与 token 分母、
paragraph_topics 只保存完整 K 维主题权重。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import delete, exists, func, insert, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Mapper

from src.chunking.spans import ParagraphSpan
from src.storage.models import (
    Chapter,
    Paragraph,
    ParagraphCurve,
    ParagraphMetric,
    ParagraphTopic,
    ParagraphTopicInference,
    TopicModelRun,
)
from src.storage.repositories.base import BaseRepository


@dataclass(frozen=True)
class ParagraphCurveRow:
    """2026-08-14 用于批量写入段落曲线（密度 + 平滑值）"""

    paragraph_id: int
    pos_density: float | None
    neg_density: float | None
    net_density: float | None
    smoothed_net_density: float | None
    surface_tension: float | None
    smoothed_surface_tension: float | None


@dataclass(frozen=True)
class ParagraphMetricRow:
    """2026-08-14 用于批量写入段落原始计数与充分统计量"""

    paragraph_id: int
    token_count: int
    char_count: int
    sentence_count: int
    sentence_char_sum: float
    sentence_char_sum_sq: float
    positive_weight_sum: float
    negative_weight_sum: float
    fight_weight_sum: float
    exclaim_count: int
    question_count: int
    pause_count: int
    dialogue_char_count: int
    sensory_hit_count: int
    imagery_hit_count: int
    metaphor_sentence_count: int
    function_word_counts: dict[str, int]
    semantic_category_counts: dict[str, int]
    surface_tension_z: float | None = None
    surface_tension: float | None = None


class ParagraphRepository(BaseRepository[Paragraph]):
    """
    段落事实源数据 Repository

    管理 run 内段落行的批量写入、查询与完整性判定，支持 run_id 过滤
    """

    def insert_paragraphs(self, run_id: str, spans: Sequence[ParagraphSpan]) -> int:
        """
        先删后插写入 run 的段落行（同 run 不可重跑前序阶段的语义）

        插入前校验段落身份、token 计数与坐标不变量，违反时抛 ValueError。

        Returns:
            本次写入的段落行数
        """
        self._validate_spans(run_id, spans)

        self.session.execute(delete(Paragraph).where(Paragraph.run_id == run_id))
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
        self.session.execute(insert(Paragraph), rows)
        return len(rows)

    def _validate_spans(self, run_id: str, spans: Sequence[ParagraphSpan]) -> None:
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

        offset_rows = self.session.execute(
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
        return self.fetch_paragraph_rows_batch(run_id, limit=None)

    def fetch_paragraph_rows_batch(
        self,
        run_id: str,
        *,
        after_id: int | None = None,
        limit: int | None = 128,
    ) -> Sequence[Row]:
        """
        按 paragraph_id keyset 游标分批读取段落行

        after_id 为上一批最后一条 paragraph_id（不含），limit 为每批行数；
        limit=None 时返回全部行（等价 fetch_paragraph_rows）。
        """
        statement = (
            select(
                Paragraph.paragraph_id,
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
            )
            .where(Paragraph.run_id == run_id)
            .order_by(Paragraph.paragraph_id)
        )
        if after_id is not None:
            statement = statement.where(Paragraph.paragraph_id > after_id)
        if limit is not None:
            statement = statement.limit(limit)
        return self.session.execute(statement).all()

    def get_incomplete_paragraph_chapter_ids(self, run_id: str) -> list[int]:
        """
        找出段落数据不完整的章节：有正文但没有任何段落行、段落序号不连续
        （min != 0 或 count != max + 1）、或坐标为空的章节，返回排序后的 chapter_id 列表
        """
        paragraph_exists = exists().where(
            (Paragraph.run_id == Chapter.run_id) & (Paragraph.chapter_id == Chapter.chapter_id)
        )
        missing_statement = (
            select(Chapter.chapter_id)
            .where(Chapter.run_id == run_id)
            # 空正文章节永远无法产出段落行，用 length(text) > 0 排除空串
            .where(func.length(Chapter.text) > 0)
            .where(~paragraph_exists)
        )
        missing_chapter_ids = {int(row.chapter_id) for row in self.session.execute(missing_statement).all()}
        count_label = func.count(Paragraph.paragraph_index)
        max_index_label = func.max(Paragraph.paragraph_index)
        min_index_label = func.min(Paragraph.paragraph_index)
        gapped_statement = (
            select(Paragraph.chapter_id)
            .where(Paragraph.run_id == run_id)
            .group_by(Paragraph.chapter_id)
            .having(or_(min_index_label != 0, count_label != max_index_label + 1))
        )
        gapped_chapter_ids = {int(row.chapter_id) for row in self.session.execute(gapped_statement).all()}
        null_statement = (
            select(Paragraph.chapter_id)
            .where(Paragraph.run_id == run_id)
            .where(
                or_(
                    Paragraph.local_start_char.is_(None),
                    Paragraph.local_end_char.is_(None),
                    Paragraph.global_start_char.is_(None),
                    Paragraph.global_end_char.is_(None),
                )
            )
            .group_by(Paragraph.chapter_id)
        )
        null_chapter_ids = {int(row.chapter_id) for row in self.session.execute(null_statement).all()}
        return sorted(missing_chapter_ids | gapped_chapter_ids | null_chapter_ids)

    # ------------------------------------------------------------------
    # paragraph_metrics（§5.3 原始计数与充分统计量）
    # ------------------------------------------------------------------

    def insert_paragraph_metrics(self, run_id: str, rows: Sequence[ParagraphMetricRow]) -> int:
        """
        先删后插写入 run 的段落指标行（同 run 不可重跑前序阶段的语义）

        surface_tension 系列由计算阶段（run 内稳健标准化后）填充，可为 None
        """
        self.session.execute(delete(ParagraphMetric).where(ParagraphMetric.run_id == run_id))
        if not rows:
            return 0
        insert_rows = [
            {
                "run_id": run_id,
                "paragraph_id": row.paragraph_id,
                "token_count": row.token_count,
                "char_count": row.char_count,
                "sentence_count": row.sentence_count,
                "sentence_char_sum": row.sentence_char_sum,
                "sentence_char_sum_sq": row.sentence_char_sum_sq,
                "positive_weight_sum": row.positive_weight_sum,
                "negative_weight_sum": row.negative_weight_sum,
                "fight_weight_sum": row.fight_weight_sum,
                "exclaim_count": row.exclaim_count,
                "question_count": row.question_count,
                "pause_count": row.pause_count,
                "dialogue_char_count": row.dialogue_char_count,
                "sensory_hit_count": row.sensory_hit_count,
                "imagery_hit_count": row.imagery_hit_count,
                "metaphor_sentence_count": row.metaphor_sentence_count,
                "function_word_counts": row.function_word_counts,
                "semantic_category_counts": row.semantic_category_counts,
                "surface_tension_z": row.surface_tension_z,
                "surface_tension": row.surface_tension,
            }
            for row in rows
        ]
        self.session.execute(insert(ParagraphMetric), insert_rows)
        return len(insert_rows)

    def fetch_paragraph_metrics(self, run_id: str) -> Sequence[Row]:
        """读取 run 的全部段落指标行，按 paragraph_id 升序"""
        statement = (
            select(
                ParagraphMetric.paragraph_id,
                ParagraphMetric.token_count,
                ParagraphMetric.char_count,
                ParagraphMetric.sentence_count,
                ParagraphMetric.sentence_char_sum,
                ParagraphMetric.sentence_char_sum_sq,
                ParagraphMetric.positive_weight_sum,
                ParagraphMetric.negative_weight_sum,
                ParagraphMetric.fight_weight_sum,
                ParagraphMetric.exclaim_count,
                ParagraphMetric.question_count,
                ParagraphMetric.pause_count,
                ParagraphMetric.dialogue_char_count,
                ParagraphMetric.sensory_hit_count,
                ParagraphMetric.imagery_hit_count,
                ParagraphMetric.metaphor_sentence_count,
                ParagraphMetric.surface_tension_z,
                ParagraphMetric.surface_tension,
            )
            .where(ParagraphMetric.run_id == run_id)
            .order_by(ParagraphMetric.paragraph_id)
        )
        return self.session.execute(statement).all()

    def has_paragraph_metrics(self, run_id: str) -> bool:
        """run 是否存在段落指标行"""
        statement = select(ParagraphMetric.paragraph_id).where(ParagraphMetric.run_id == run_id).limit(1)
        return self.session.execute(statement).scalar_one_or_none() is not None

    # ------------------------------------------------------------------
    # 主题链路（§5.8 topic_model_runs / §5.9 inference / §5.10 paragraph_topics）
    # ------------------------------------------------------------------

    def insert_topic_model_run(
        self,
        run_id: str,
        *,
        model_key: str,
        library_version: str,
        pipeline_version: str,
        num_topics: int,
        parameters: dict[str, Any],
        dictionary_size: int,
        training_document_count: int,
        inference_paragraph_count: int,
        artifact_key: str,
    ) -> None:
        """先清后插写入 run 的主题模型契约（同 run 重跑语义是"重新计算"）"""
        self.session.execute(delete(TopicModelRun).where(TopicModelRun.run_id == run_id))
        self.session.execute(
            insert(TopicModelRun),
            {
                "run_id": run_id,
                "model_key": model_key,
                "library_version": library_version,
                "pipeline_version": pipeline_version,
                "num_topics": num_topics,
                "parameters": parameters,
                "dictionary_size": dictionary_size,
                "training_document_count": training_document_count,
                "inference_paragraph_count": inference_paragraph_count,
                "artifact_key": artifact_key,
            },
        )

    def fetch_topic_model_run(self, run_id: str) -> TopicModelRun | None:
        """读取 run 的主题模型契约行"""
        statement = select(TopicModelRun).where(TopicModelRun.run_id == run_id)
        return self.session.execute(statement).scalar_one_or_none()

    def insert_paragraph_topic_inferences(
        self,
        run_id: str,
        rows: Sequence[tuple[int, int, int, str, str | None, float | None]],
    ) -> int:
        """
        先清后插写入 run 的段落推断状态（每段一行）

        rows: (paragraph_id, source_token_count, inference_token_count,
               inference_status, unavailable_reason, distribution_sum)

        """
        inference_rows = [
            {
                "run_id": run_id,
                "paragraph_id": paragraph_id,
                "source_token_count": source_token_count,
                "inference_token_count": inference_token_count,
                "inference_status": inference_status,
                "unavailable_reason": unavailable_reason,
                "distribution_sum": distribution_sum,
            }
            for (
                paragraph_id,
                source_token_count,
                inference_token_count,
                inference_status,
                unavailable_reason,
                distribution_sum,
            ) in rows
        ]
        if not inference_rows:
            return 0
        self.session.execute(
            delete(ParagraphTopicInference).where(ParagraphTopicInference.run_id == run_id)
        )
        self.session.bulk_insert_mappings(cast(Mapper[Any], ParagraphTopicInference), inference_rows)
        return len(inference_rows)

    def clear_paragraph_topic_inferences(self, run_id: str) -> None:
        """清空 run 的段落推断状态行"""
        self.session.execute(delete(ParagraphTopicInference).where(ParagraphTopicInference.run_id == run_id))

    def fetch_paragraph_topic_inferences(self, run_id: str) -> Sequence[Row]:
        """读取 run 的全部段落推断状态行（按段落排序）"""
        statement = (
            select(
                ParagraphTopicInference.paragraph_id,
                ParagraphTopicInference.source_token_count,
                ParagraphTopicInference.inference_token_count,
                ParagraphTopicInference.inference_status,
                ParagraphTopicInference.unavailable_reason,
                ParagraphTopicInference.distribution_sum,
            )
            .where(ParagraphTopicInference.run_id == run_id)
            .order_by(ParagraphTopicInference.paragraph_id)
        )
        return self.session.execute(statement).all()

    def fetch_topic_inference_total(self, run_id: str) -> int | None:
        """全书主题推断分母：所有段落（每段一行）的 inference_token_count 之和"""
        return self.session.execute(
            select(func.sum(ParagraphTopicInference.inference_token_count)).where(
                ParagraphTopicInference.run_id == run_id
            )
        ).scalar_one_or_none()

    def fetch_chapter_inference_totals(self, run_id: str) -> Sequence[Row]:
        """按章节返回推断 token 分母（每段一行，§5.11 章节聚合分母）"""
        stmt = (
            select(
                Chapter.chapter_id,
                func.sum(ParagraphTopicInference.inference_token_count).label("token_total"),
            )
            .select_from(Chapter)
            .join(Paragraph, (Paragraph.run_id == Chapter.run_id) & (Paragraph.chapter_id == Chapter.chapter_id))
            .join(
                ParagraphTopicInference,
                (ParagraphTopicInference.run_id == Paragraph.run_id)
                & (ParagraphTopicInference.paragraph_id == Paragraph.paragraph_id),
            )
            .where(Paragraph.run_id == run_id)
            .group_by(Chapter.chapter_id)
        )
        return self.session.execute(stmt).all()

    def fetch_topic_emotion_aggregates(self, run_id: str) -> Sequence[Row]:
        """主题-情感分子分母（§5.11）：net_density 空值段落在 SQL 层同时排除"""
        stmt = (
            select(
                ParagraphTopic.topic_id,
                func.sum(
                    ParagraphTopic.topic_weight
                    * ParagraphTopicInference.inference_token_count
                    * ParagraphCurve.net_density
                ).label("emotion_total"),
                func.sum(ParagraphTopic.topic_weight * ParagraphTopicInference.inference_token_count).label(
                    "weighted_token_total"
                ),
            )
            .join(
                ParagraphTopicInference,
                (ParagraphTopicInference.run_id == ParagraphTopic.run_id)
                & (ParagraphTopicInference.paragraph_id == ParagraphTopic.paragraph_id),
            )
            .join(
                ParagraphCurve,
                (ParagraphCurve.run_id == ParagraphTopic.run_id)
                & (ParagraphCurve.paragraph_id == ParagraphTopic.paragraph_id),
            )
            .where(ParagraphTopic.run_id == run_id, ParagraphCurve.net_density.is_not(None))
            .group_by(ParagraphTopic.topic_id)
            .order_by(ParagraphTopic.topic_id)
        )
        return self.session.execute(stmt).all()

    def insert_paragraph_topics(
        self,
        run_id: str,
        rows: Sequence[tuple[int, int, float]],
    ) -> int:
        """
        先清后插写入 run 的段落主题行（同 run 重跑语义是"重新计算"）

        rows: (paragraph_id, topic_id, topic_weight)；完整 K 维分布由调用方保证，
        token 分母不在此表重复保存（§5.10）

        """
        topic_rows = [
            {
                "run_id": run_id,
                "paragraph_id": paragraph_id,
                "topic_id": topic_id,
                "topic_weight": topic_weight,
            }
            for paragraph_id, topic_id, topic_weight in rows
        ]
        if not topic_rows:
            return 0
        self.session.execute(delete(ParagraphTopic).where(ParagraphTopic.run_id == run_id))
        self.session.bulk_insert_mappings(cast(Mapper[Any], ParagraphTopic), topic_rows)
        return len(topic_rows)

    def clear_paragraph_topics(self, run_id: str) -> None:
        """清空 run 的段落主题行"""
        self.session.execute(delete(ParagraphTopic).where(ParagraphTopic.run_id == run_id))

    def fetch_paragraph_topics(self, run_id: str) -> Sequence[Row]:
        """读取 run 的全部段落主题行（按段落与主题排序）"""
        statement = (
            select(
                ParagraphTopic.paragraph_id,
                ParagraphTopic.topic_id,
                ParagraphTopic.topic_weight,
            )
            .where(ParagraphTopic.run_id == run_id)
            .order_by(ParagraphTopic.paragraph_id, ParagraphTopic.topic_id)
        )
        return self.session.execute(statement).all()

    def fetch_paragraph_topics_agg(self, run_id: str) -> Sequence[Row]:
        """
        全书主题分子：按主题返回 token 加权和（§5.11）

        分母为全书所有段落的 inference_token_count 之和（每段一行），
        由 fetch_topic_inference_total 提供；归一化在调用方完成。
        禁止对段落等权求和。
        """
        stmt = (
            select(
                ParagraphTopic.topic_id,
                func.sum(ParagraphTopic.topic_weight * ParagraphTopicInference.inference_token_count).label(
                    "weighted_total"
                ),
            )
            .join(
                ParagraphTopicInference,
                (ParagraphTopicInference.run_id == ParagraphTopic.run_id)
                & (ParagraphTopicInference.paragraph_id == ParagraphTopic.paragraph_id),
            )
            .where(ParagraphTopic.run_id == run_id)
            .group_by(ParagraphTopic.topic_id)
        )
        return self.session.execute(stmt).all()

    def fetch_chapter_topic_aggregates(self, run_id: str) -> Sequence[Row]:
        """
        章节主题分子：按章节返回主题 token 加权和（§5.11）

        章节边界用 paragraphs.chapter_id 关联 chapters 并按 chapters.sequence
        排序，不使用段落列表下标推断章节；分母与归一化在调用方完成。

        """
        stmt = (
            select(
                Chapter.chapter_id,
                Chapter.sequence,
                Chapter.title,
                ParagraphTopic.topic_id,
                func.sum(ParagraphTopic.topic_weight * ParagraphTopicInference.inference_token_count).label(
                    "weighted_total"
                ),
            )
            .select_from(Chapter)
            .join(Paragraph, (Paragraph.run_id == Chapter.run_id) & (Paragraph.chapter_id == Chapter.chapter_id))
            .join(
                ParagraphTopicInference,
                (ParagraphTopicInference.run_id == Paragraph.run_id)
                & (ParagraphTopicInference.paragraph_id == Paragraph.paragraph_id),
            )
            .join(
                ParagraphTopic,
                (ParagraphTopic.run_id == Paragraph.run_id)
                & (ParagraphTopic.paragraph_id == Paragraph.paragraph_id),
            )
            .where(Paragraph.run_id == run_id)
            .group_by(Chapter.chapter_id, Chapter.sequence, Chapter.title, ParagraphTopic.topic_id)
            .order_by(Chapter.sequence, ParagraphTopic.topic_id)
        )
        return self.session.execute(stmt).all()

    def fetch_paragraph_topic_rows(self, run_id: str) -> Sequence[Row]:
        """
        段落主题序列数据（§5.11）：段落真实字符位置、章节序列与
        推断 token 数齐备

        返回: (paragraph_id, chapter_id, chapter_sequence, global_start_char,
               inference_token_count, topic_id, topic_weight)
        """
        stmt = (
            select(
                Paragraph.paragraph_id,
                Paragraph.chapter_id,
                Chapter.sequence,
                Paragraph.global_start_char,
                ParagraphTopicInference.inference_token_count,
                ParagraphTopic.topic_id,
                ParagraphTopic.topic_weight,
            )
            .join(
                ParagraphTopicInference,
                (ParagraphTopicInference.run_id == Paragraph.run_id)
                & (ParagraphTopicInference.paragraph_id == Paragraph.paragraph_id),
            )
            .join(
                ParagraphTopic,
                (ParagraphTopic.run_id == Paragraph.run_id)
                & (ParagraphTopic.paragraph_id == Paragraph.paragraph_id),
            )
            .join(Chapter, (Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Chapter.chapter_id))
            .where(Paragraph.run_id == run_id)
            .order_by(Paragraph.global_start_char, ParagraphTopic.topic_id)
        )
        return self.session.execute(stmt).all()

    # ------------------------------------------------------------------
    # paragraph_curves（§5.5 段落曲线）
    # ------------------------------------------------------------------

    def insert_paragraph_curves(self, run_id: str, rows: Sequence[ParagraphCurveRow]) -> int:
        """
        先删后插写入 run 的段落曲线行

        密度列在分母为 0 时为 None（合法观测，不伪造为零）
        """
        self.session.execute(delete(ParagraphCurve).where(ParagraphCurve.run_id == run_id))
        if not rows:
            return 0
        insert_rows = [
            {
                "run_id": run_id,
                "paragraph_id": row.paragraph_id,
                "pos_density": row.pos_density,
                "neg_density": row.neg_density,
                "net_density": row.net_density,
                "smoothed_net_density": row.smoothed_net_density,
                "surface_tension": row.surface_tension,
                "smoothed_surface_tension": row.smoothed_surface_tension,
            }
            for row in rows
        ]
        self.session.execute(insert(ParagraphCurve), insert_rows)
        return len(insert_rows)

    def fetch_paragraph_curves(self, run_id: str) -> Sequence[Row]:
        """读取 run 的全部段落曲线行，按 paragraph_id 升序"""
        statement = (
            select(
                ParagraphCurve.paragraph_id,
                ParagraphCurve.pos_density,
                ParagraphCurve.neg_density,
                ParagraphCurve.net_density,
                ParagraphCurve.smoothed_net_density,
                ParagraphCurve.surface_tension,
                ParagraphCurve.smoothed_surface_tension,
            )
            .where(ParagraphCurve.run_id == run_id)
            .order_by(ParagraphCurve.paragraph_id)
        )
        return self.session.execute(statement).all()

    def fetch_chapter_metric_aggregates(self, run_id: str) -> list[tuple[int, dict[str, float]]]:
        """
        按章聚合段落指标充分统计量（§9.1 分子/分母守恒）

        每行返回 (chapter_id, 字段名 → 数值) 的聚合结果，供聚合 fetchers 与
        质量门使用：密度类比率一律在目标粒度上重新求分子之和/分母之和，
        不做等权平均。
        """
        statement = (
            select(
                Paragraph.chapter_id.label("chapter_id"),
                func.sum(ParagraphMetric.token_count).label("token_count"),
                func.sum(ParagraphMetric.char_count).label("char_count"),
                func.sum(ParagraphMetric.sentence_count).label("sentence_count"),
                func.sum(ParagraphMetric.sentence_char_sum).label("sentence_char_sum"),
                func.sum(ParagraphMetric.positive_weight_sum).label("positive_weight_sum"),
                func.sum(ParagraphMetric.negative_weight_sum).label("negative_weight_sum"),
                func.sum(ParagraphMetric.dialogue_char_count).label("dialogue_char_count"),
                func.sum(ParagraphMetric.imagery_hit_count).label("imagery_hit_count"),
            )
            .join(
                Paragraph,
                (Paragraph.run_id == ParagraphMetric.run_id) & (Paragraph.paragraph_id == ParagraphMetric.paragraph_id),
            )
            .join(
                Chapter,
                (Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Paragraph.chapter_id),
            )
            .where(ParagraphMetric.run_id == run_id)
            .group_by(Paragraph.chapter_id, Chapter.sequence)
            .order_by(Chapter.sequence, Paragraph.chapter_id)
        )
        rows = self.session.execute(statement).all()
        return [(int(row.chapter_id), {key: float(value) for key, value in row._mapping.items()}) for row in rows]

    def fetch_chapter_tension_scores(self, run_id: str) -> list[tuple[int, float]]:
        """
        每章张力 = 章内段落 surface_tension 均值（供 timeline/聚合使用）

        段落表面张力已是 run 内稳健标准化 + sigmoid 后的 [0,1] 值，
        章节值取段落均值（缺失张力数据的章由调用方兜底）。
        """
        statement = (
            select(
                Paragraph.chapter_id.label("chapter_id"),
                func.avg(ParagraphCurve.surface_tension).label("avg_tension"),
            )
            .join(
                ParagraphCurve,
                (ParagraphCurve.run_id == Paragraph.run_id) & (ParagraphCurve.paragraph_id == Paragraph.paragraph_id),
            )
            .join(
                Chapter,
                (Chapter.run_id == Paragraph.run_id) & (Chapter.chapter_id == Paragraph.chapter_id),
            )
            .where(
                Paragraph.run_id == run_id,
                ParagraphCurve.surface_tension.is_not(None),
            )
            .group_by(Paragraph.chapter_id, Chapter.sequence)
            .order_by(Chapter.sequence, Paragraph.chapter_id)
        )
        rows = self.session.execute(statement).all()
        return [(int(row.chapter_id), float(row.avg_tension)) for row in rows]

    def has_paragraph_curves(self, run_id: str) -> bool:
        """run 是否存在段落曲线行"""
        statement = select(ParagraphCurve.paragraph_id).where(ParagraphCurve.run_id == run_id).limit(1)
        return self.session.execute(statement).scalar_one_or_none() is not None
