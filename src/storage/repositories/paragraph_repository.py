"""
段落事实源存储与检索

paragraphs 是全文唯一的段落事实源（设计文档《章节粒度分析指标重设计》§5.1），
本仓储负责段落行的写入（先删后插）、完整性检查与按 run 读取，
并管理段落级派生数据表：paragraph_metrics（原始计数与充分统计量，§5.3）、
paragraph_topics（段落 LDA 主题，§5.4）与 paragraph_curves（段落曲线，§5.5）。

主题链路按《分析能力扩展路线图》§5.8-5.10：topic_model_runs 保存模型契约、
paragraph_topic_inference 每段一行保存推断状态与 token 分母、
paragraph_topics 只保存完整 K 维主题权重。

2026-10-02 拆分说明（Trae）：实现迁移至 paragraph/ 子包模块函数
（rows/writer/reader/metrics_ops/curve_ops/topic_ops，接收 session 参数），
本模块保留 ParagraphRepository 门面（方法体一行委托）并 re-export
ParagraphCurveRow/ParagraphMetricRow，44 个导入方零改动。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.engine import Row

from src.storage.input_records import ParagraphRecord as ParagraphSpan
from src.storage.models import Paragraph, TopicModelRun
from src.storage.repositories.base import BaseRepository
from src.storage.repositories.paragraph.curve_ops import (
    fetch_chapter_tension_scores,
    fetch_paragraph_curves,
    has_paragraph_curves,
    insert_paragraph_curves,
)
from src.storage.repositories.paragraph.metrics_ops import (
    fetch_chapter_metric_aggregates,
    fetch_paragraph_metrics,
    has_paragraph_metrics,
    insert_paragraph_metrics,
)
from src.storage.repositories.paragraph.reader import (
    count_paragraphs,
    fetch_paragraph_rows_batch,
    has_paragraphs,
)
from src.storage.repositories.paragraph.rows import ParagraphCurveRow, ParagraphMetricRow
from src.storage.repositories.paragraph.topic_ops import (
    clear_paragraph_topic_inferences,
    clear_paragraph_topics,
    fetch_chapter_inference_totals,
    fetch_chapter_topic_aggregates,
    fetch_paragraph_topic_rows,
    fetch_paragraph_topics_agg,
    fetch_topic_emotion_aggregates,
    fetch_topic_inference_total,
    fetch_topic_model_run,
    insert_paragraph_topic_inferences,
    insert_paragraph_topics,
    insert_topic_model_run,
)
from src.storage.repositories.paragraph.writer import insert_paragraphs, validate_spans


class ParagraphRepository(BaseRepository[Paragraph]):
    """
    段落事实源数据 Repository

    管理 run 内段落行的批量写入、查询与完整性判定，支持 run_id 过滤

    2026-10-02 拆分说明：方法实现位于 paragraph/ 子包（函数接收 session 参数），
    本类保留为门面，方法体为一行委托，对外接口与行为不变。
    """

    def insert_paragraphs(self, run_id: str, spans: Sequence[ParagraphSpan]) -> int:
        """先删后插写入 run 的段落行（插入前校验不变量）"""
        return insert_paragraphs(self.session, run_id, spans)

    def _validate_spans(self, run_id: str, spans: Sequence[ParagraphSpan]) -> None:
        """写入前校验段落身份、token 与坐标不变量"""
        validate_spans(self.session, run_id, spans)

    def has_paragraphs(self, run_id: str) -> bool:
        """run 是否存在段落行"""
        return has_paragraphs(self.session, run_id)

    def count_paragraphs(self, run_id: str) -> int:
        """统计指定 run 的段落行数"""
        return count_paragraphs(self.session, run_id)

    def fetch_paragraph_rows(self, run_id: str) -> Sequence[Row]:
        """读取 run 的全部段落行，按 paragraph_id 升序"""
        return self.fetch_paragraph_rows_batch(run_id, limit=None)

    def fetch_paragraph_rows_batch(
        self,
        run_id: str,
        *,
        chapter_id: int | None = None,
        after_id: int | None = None,
        limit: int | None = 128,
    ) -> Sequence[Row]:
        """按 paragraph_id keyset 游标分批读取段落行"""
        return fetch_paragraph_rows_batch(self.session, run_id, chapter_id=chapter_id, after_id=after_id, limit=limit)

    # ------------------------------------------------------------------
    # paragraph_metrics（§5.3 原始计数与充分统计量）
    # ------------------------------------------------------------------

    def insert_paragraph_metrics(self, run_id: str, rows: Sequence[ParagraphMetricRow]) -> int:
        """先删后插写入 run 的段落指标行（surface_tension 系列可为 None）"""
        return insert_paragraph_metrics(self.session, run_id, rows)

    def fetch_paragraph_metrics(self, run_id: str) -> Sequence[Row]:
        """读取 run 的全部段落指标行，按 paragraph_id 升序"""
        return fetch_paragraph_metrics(self.session, run_id)

    def has_paragraph_metrics(self, run_id: str) -> bool:
        """run 是否存在段落指标行"""
        return has_paragraph_metrics(self.session, run_id)

    def fetch_chapter_metric_aggregates(self, run_id: str) -> list[tuple[int, dict[str, float]]]:
        """按章聚合段落指标充分统计量（§9.1 分子/分母守恒）"""
        return fetch_chapter_metric_aggregates(self.session, run_id)

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
        insert_topic_model_run(
            self.session,
            run_id,
            model_key=model_key,
            library_version=library_version,
            pipeline_version=pipeline_version,
            num_topics=num_topics,
            parameters=parameters,
            dictionary_size=dictionary_size,
            training_document_count=training_document_count,
            inference_paragraph_count=inference_paragraph_count,
            artifact_key=artifact_key,
        )

    def fetch_topic_model_run(self, run_id: str) -> TopicModelRun | None:
        """读取 run 的主题模型契约行"""
        return fetch_topic_model_run(self.session, run_id)

    def insert_paragraph_topic_inferences(
        self,
        run_id: str,
        rows: Sequence[tuple[int, int, int, str, str | None, float | None]],
    ) -> int:
        """先清后插写入 run 的段落推断状态（每段一行）"""
        return insert_paragraph_topic_inferences(self.session, run_id, rows)

    def clear_paragraph_topic_inferences(self, run_id: str) -> None:
        """清空 run 的段落推断状态行"""
        clear_paragraph_topic_inferences(self.session, run_id)

    def fetch_topic_inference_total(self, run_id: str) -> int | None:
        """全书主题推断分母：所有段落（每段一行）的 inference_token_count 之和"""
        return fetch_topic_inference_total(self.session, run_id)

    def fetch_chapter_inference_totals(self, run_id: str) -> Sequence[Row]:
        """按章节返回推断 token 分母（每段一行，§5.11 章节聚合分母）"""
        return fetch_chapter_inference_totals(self.session, run_id)

    def fetch_topic_emotion_aggregates(self, run_id: str) -> Sequence[Row]:
        """主题-情感分子分母（§5.11）：net_density 空值段落在 SQL 层同时排除"""
        return fetch_topic_emotion_aggregates(self.session, run_id)

    def insert_paragraph_topics(
        self,
        run_id: str,
        rows: Sequence[tuple[int, int, float]],
    ) -> int:
        """先清后插写入 run 的段落主题行（同 run 重跑语义是"重新计算"）"""
        return insert_paragraph_topics(self.session, run_id, rows)

    def clear_paragraph_topics(self, run_id: str) -> None:
        """清空 run 的段落主题行"""
        clear_paragraph_topics(self.session, run_id)

    def fetch_paragraph_topics_agg(self, run_id: str) -> Sequence[Row]:
        """全书主题分子：按主题返回 token 加权和（§5.11，禁止对段落等权求和）"""
        return fetch_paragraph_topics_agg(self.session, run_id)

    def fetch_chapter_topic_aggregates(self, run_id: str) -> Sequence[Row]:
        """章节主题分子：按章节返回主题 token 加权和（§5.11）"""
        return fetch_chapter_topic_aggregates(self.session, run_id)

    def fetch_paragraph_topic_rows(self, run_id: str) -> Sequence[Row]:
        """段落主题序列数据（§5.11）：段落真实字符位置、章节序列与推断 token 数齐备"""
        return fetch_paragraph_topic_rows(self.session, run_id)

    # ------------------------------------------------------------------
    # paragraph_curves（§5.5 段落曲线）
    # ------------------------------------------------------------------

    def insert_paragraph_curves(self, run_id: str, rows: Sequence[ParagraphCurveRow]) -> int:
        """先删后插写入 run 的段落曲线行（密度列分母为 0 时为 None）"""
        return insert_paragraph_curves(self.session, run_id, rows)

    def fetch_paragraph_curves(self, run_id: str) -> Sequence[Row]:
        """读取 run 的全部段落曲线行，按 paragraph_id 升序"""
        return fetch_paragraph_curves(self.session, run_id)

    def fetch_chapter_tension_scores(self, run_id: str) -> list[tuple[int, float]]:
        """每章张力 = 章内段落 surface_tension 均值（供 timeline/聚合使用）"""
        return fetch_chapter_tension_scores(self.session, run_id)

    def has_paragraph_curves(self, run_id: str) -> bool:
        """run 是否存在段落曲线行"""
        return has_paragraph_curves(self.session, run_id)
