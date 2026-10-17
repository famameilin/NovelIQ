"""
CLI aggregate 模块测试

创建时间: 2025-03-11
任务: 测试聚合流程

修改时间: 2026-03-15
任务: storage-layer-decoupling
修改内容: 使用 SessionFactory 替代 connect_db/create_tables，消除 DeprecationWarning

修改时间: 2026-03-15
任务: postgresql-migration
修改内容: 使用 SQLAlchemy text() 替换 ? 占位符，移除 sqlite3 导入

修改时间: 2026-03-15
任务: postgresql-migration-cleanup
修改内容: 改用 PostgreSQL db_session fixture，移除 SessionFactory 依赖

修改时间: 2026-08-14
任务: M8b 段落化
修改内容: 聚合阶段不再写入 chunk_curves（曲线事实源为 paragraph_curves），
测试夹具改为插入段落事实源 + 段落指标 + 段落曲线，断言 global_stats 守恒聚合。

修改时间: 2026-10-16
任务: 全库第三范式改造收尾
修改内容: 段落指标行只带 paragraph_metrics 可写列；张力以 paragraph_features 的
tension_z 观测表达（sigmoid 为读投影）；全书统计改读 analysis_runs 具名列，
断言保留守恒与 run 隔离行为面。
"""

import sys
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.storage.repositories import ChapterRepository, RunRepository, StatsRepository
from src.storage.repositories.paragraph import insert_paragraph_tension_observations
from src.storage.repositories.paragraph_repository import (
    ParagraphCurveRow,
    ParagraphMetricRow,
    ParagraphRepository,
)
from src.text_processing.models import Chunk
from src.text_processing.paragraphs import split_chunk_paragraphs
from src.workflows.aggregate import run_aggregate
from tests.support.analysis_factories import insert_test_novel
from tests.support.chapter_annotation_helpers import confirm_test_work, persist_chapter_annotation


def _build_paragraph_rows(
    chunks: list[Chunk],
) -> tuple[list, list, list, list]:
    """按章节构造段落事实源 + 段落指标 + 曲线平滑样本 + 张力 z 观测（每章一个段落）。

    2026-10-16 3NF：指标行只带 paragraph_metrics 的可写列；表面张力以正式
    z 观测（paragraph_features.tension_z）表达，sigmoid 展示值由读取投影给出。
    """
    spans = [replace(span, token_count=10) for span in split_chunk_paragraphs(chunks, max_chars=1500)]
    metric_rows: list[ParagraphMetricRow] = []
    curve_rows: list[ParagraphCurveRow] = []
    tension_rows: list[tuple[int, float]] = []
    for span in spans:
        metric_rows.append(
            ParagraphMetricRow(
                paragraph_id=span.paragraph_id,
                token_count=10,
                sentence_count=2,
                sentence_char_sum=40.0,
                sentence_char_sum_sq=900.0,
                positive_weight_sum=1.0,
                negative_weight_sum=0.5,
                fight_weight_sum=0.0,
                exclaim_count=1,
                question_count=0,
                pause_count=2,
                dialogue_char_count=5,
                sensory_hit_count=0,
                imagery_hit_count=1,
                metaphor_sentence_count=0,
                body_reaction_hit_count=0,
            )
        )
        curve_rows.append(
            ParagraphCurveRow(
                paragraph_id=span.paragraph_id,
                pos_density=None,
                neg_density=None,
                net_density=None,
                smoothed_net_density=0.05,
                surface_tension=None,
                smoothed_surface_tension=0.5,
            )
        )
        # z=0 → 任意标准 sigmoid 的中点值 0.5，断言与投影公式细节解耦
        tension_rows.append((span.paragraph_id, 0.0))
    return spans, metric_rows, curve_rows, tension_rows


def _insert_paragraph_facts(session, run_id: str, chunks: list[Chunk]) -> None:
    """写入段落事实源、指标、曲线平滑样本与张力 z 观测（各经正式入口，先删后插语义）"""
    spans, metric_rows, curve_rows, tension_rows = _build_paragraph_rows(chunks)
    paragraph_repo = ParagraphRepository(session)
    paragraph_repo.insert_paragraphs(run_id, spans)
    paragraph_repo.insert_paragraph_metrics(run_id, metric_rows)
    paragraph_repo.insert_paragraph_curves(run_id, curve_rows)
    insert_paragraph_tension_observations(session, run_id, tension_rows)


class TestAggregate:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(self.novel_id, session=db_session)

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def _create_chunks_with_paragraphs(self, chunk_count: int) -> None:
        chapter_repo = ChapterRepository(self.db_session)
        texts = [f"这是第{i}个测试文本。包含快乐和悲伤的词语。" for i in range(chunk_count)]
        chunks: list[Chunk] = []
        offset = 0
        for i, chunk_text in enumerate(texts):
            chunks.append(Chunk(index=i, start=offset, end=offset + len(chunk_text), text=chunk_text, chapter_id=i + 1))
            offset += len(chunk_text)
        chapter_repo.insert_chapter_texts(self.run_id, chunks)

        _insert_paragraph_facts(self.db_session, self.run_id, chunks)
        confirm_test_work(self.db_session, self.run_id, create_missing=True)

    @pytest.mark.asyncio()
    async def test_aggregate_basic(self) -> None:
        self._create_chunks_with_paragraphs(5)

        chunks, stats_count, reserved = await run_aggregate(run_id=self.run_id, session=self.db_session)
        assert chunks == 5
        assert stats_count > 0
        assert reserved == 0

        # 全书统计按运行落在 analysis_runs 具名列（16 项目录内已计算项非空）
        persisted = StatsRepository(self.db_session).fetch_global_stats_dict(self.run_id)
        assert persisted

    @pytest.mark.asyncio()
    async def test_aggregate_global_stats(self) -> None:
        self._create_chunks_with_paragraphs(5)

        await run_aggregate(run_id=self.run_id, session=self.db_session)

        by_name = StatsRepository(self.db_session).fetch_global_stats_dict(self.run_id)

        # §9.1 守恒：全书情绪密度 = (Σpos − Σneg) / Σtoken
        assert by_name["emotion_avg"] == pytest.approx((5 * 1.0 - 5 * 0.5) / (5 * 10))
        # 平均句长 = Σsentence_char_sum / Σsentence_count
        assert by_name["avg_sent_len"] == pytest.approx(40.0 / 2)
        # 章张力均值 = 段落表面张力均值（z=0 经 sigmoid 投影为 0.5）
        assert by_name["rhythm_avg"] == pytest.approx(0.5)
        assert by_name["rhythm_std"] == pytest.approx(0.0)
        assert by_name["rhythm_max"] == pytest.approx(0.5)
        assert by_name["rhythm_min"] == pytest.approx(0.5)

    @pytest.mark.asyncio()
    async def test_aggregate_with_annotations(self) -> None:
        chapter_repo = ChapterRepository(self.db_session)
        texts = [f"测试文本{i}" for i in range(3)]
        test_chunks: list[Chunk] = []
        offset = 0
        for i, chunk_text in enumerate(texts):
            test_chunks.append(
                Chunk(index=i, start=offset, end=offset + len(chunk_text), text=chunk_text, chapter_id=i + 1)
            )
            offset += len(chunk_text)
        chapter_repo.insert_chapter_texts(self.run_id, test_chunks)

        _insert_paragraph_facts(self.db_session, self.run_id, test_chunks)

        persist_chapter_annotation(
            self.db_session,
            run_id=self.run_id,
            chapter_id=1,
            emotional_valences={0: 2, 1: 1, 2: 1},
            event_types={0: "冲突", 1: "铺垫", 2: "铺垫"},
            pivot_chapters={0},
            cliffhanger_chapters={2},
        )

        confirm_test_work(self.db_session, self.run_id, create_missing=True)
        chunks, stats_count, _ = await run_aggregate(run_id=self.run_id, session=self.db_session)
        assert chunks == 3
        assert stats_count > 0

    @pytest.mark.asyncio()
    async def test_aggregate_empty_db(self) -> None:
        confirm_test_work(self.db_session, self.run_id, create_missing=True)
        with pytest.raises(ValueError, match="必需角色 work"):
            await run_aggregate(run_id=self.run_id, session=self.db_session)

    @pytest.mark.asyncio()
    async def test_aggregate_metrics_graph_not_ready_degrades_gracefully(self, monkeypatch) -> None:
        """2026-08-13 P2-3 用于验证 aggregate_all_metrics 抛 GraphReadinessError 时
        保留降级（全书统计正常写入）且记录 error 级别日志"""
        from unittest.mock import patch

        from src.api.exceptions import GraphReadinessError

        self._create_chunks_with_paragraphs(3)
        messages: list[str] = []

        def _capture(message: str) -> None:
            messages.append(str(message))

        monkeypatch.setattr("src.workflows.aggregate.logger.error", _capture)
        with patch(
            "src.workflows.aggregate.query_aggregate_metrics",
            side_effect=GraphReadinessError("graph not ready yet"),
        ):
            chunks, stats_count, _ = await run_aggregate(
                run_id=self.run_id,
                session=self.db_session,
            )

        assert chunks == 3
        assert stats_count > 0
        assert any("graph not ready yet" in message for message in messages)


class TestGlobalStatsRunIsolation:
    """2026-08-13 修复 P1：compute_global_stats 此前查询 chunk_style 缺 run_id 过滤，
    跨 run 累积的数据会污染当前 run 的 avg_* 指标（M8b 后改为段落充分统计量聚合）。"""

    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(self.novel_id, session=db_session)
        run_repo = RunRepository(db_session)
        self.run_a = run_repo.create_run(novel_id=self.novel_id)
        self.run_b = run_repo.create_run(novel_id=self.novel_id)

    def _insert_metrics_for_run(self, run_id: str, sentence_sum: float, sentence_count: int) -> None:
        """每个 run 插入 1 章 1 段；句长充分统计量不同用于区分 run。"""
        chapter_repo = ChapterRepository(self.db_session)
        chunk_text = "测试文本内容。"
        chapter_repo.insert_chapter_texts(
            run_id,
            [Chunk(index=0, start=0, end=len(chunk_text), text=chunk_text, chapter_id=1)],
        )
        spans, metric_rows, curve_rows, tension_rows = _build_paragraph_rows(
            [Chunk(index=0, start=0, end=len(chunk_text), text=chunk_text, chapter_id=1)]
        )
        metric_rows = [
            replace(
                row,
                sentence_char_sum=sentence_sum,
                sentence_count=sentence_count,
            )
            for row in metric_rows
        ]
        paragraph_repo = ParagraphRepository(self.db_session)
        paragraph_repo.insert_paragraphs(run_id, spans)
        paragraph_repo.insert_paragraph_metrics(run_id, metric_rows)
        paragraph_repo.insert_paragraph_curves(run_id, curve_rows)
        insert_paragraph_tension_observations(self.db_session, run_id, tension_rows)

    def test_global_stats_only_aggregates_own_run(self) -> None:
        from src.metrics.queries.global_stats import query_global_stats as compute_global_stats

        self._insert_metrics_for_run(self.run_a, sentence_sum=20.0, sentence_count=1)
        self._insert_metrics_for_run(self.run_b, sentence_sum=100.0, sentence_count=2)

        stats_a = dict(compute_global_stats(self.db_session, self.run_a))
        stats_b = dict(compute_global_stats(self.db_session, self.run_b))

        # run_b 的句长统计不得污染 run_a 的均值
        assert stats_a["avg_sent_len"] == pytest.approx(20.0)
        assert stats_b["avg_sent_len"] == pytest.approx(50.0)
