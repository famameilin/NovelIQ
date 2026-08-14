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
"""

import sys
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import Chunk, split_chunk_paragraphs
from src.storage.repositories import ChunkRepository, RunRepository
from src.storage.repositories.paragraph_repository import (
    ParagraphCurveRow,
    ParagraphMetricRow,
    ParagraphRepository,
)
from src.workflows.aggregate import run_aggregate
from tests.support.analysis_factories import insert_test_novel
from tests.support.chapter_annotation_helpers import persist_chapter_annotation


def _build_paragraph_rows(
    chunks: list[Chunk],
) -> tuple[list, list, list]:
    """按章节构造段落事实源 + 段落指标 + 段落曲线（每章一个段落）。"""
    spans = [
        replace(span, token_count=10)
        for span in split_chunk_paragraphs(chunks, max_chars=1500)
    ]
    metric_rows: list[ParagraphMetricRow] = []
    curve_rows: list[ParagraphCurveRow] = []
    for index, span in enumerate(spans):
        metric_rows.append(
            ParagraphMetricRow(
                paragraph_id=span.paragraph_id,
                token_count=10,
                char_count=span.char_count,
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
                function_word_counts={},
                semantic_category_counts={},
                surface_tension_z=0.0,
                surface_tension=0.3 + index * 0.1,
            )
        )
        curve_rows.append(
            ParagraphCurveRow(
                paragraph_id=span.paragraph_id,
                pos_density=0.1,
                neg_density=0.05,
                net_density=0.05,
                smoothed_net_density=0.05,
                surface_tension=0.3 + index * 0.1,
                smoothed_surface_tension=0.3 + index * 0.1,
            )
        )
    return spans, metric_rows, curve_rows


class TestAggregate:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(self.novel_id, session=db_session)

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def _create_chunks_with_paragraphs(self, chunk_count: int) -> None:
        chunk_repo = ChunkRepository(self.db_session)
        texts = [f"这是第{i}个测试文本。包含快乐和悲伤的词语。" for i in range(chunk_count)]
        chunks: list[Chunk] = []
        offset = 0
        for i, chunk_text in enumerate(texts):
            chunks.append(Chunk(index=i, start=offset, end=offset + len(chunk_text), text=chunk_text, chapter_id=i + 1))
            offset += len(chunk_text)
        chunk_repo.insert_chunks(self.run_id, chunks)

        spans, metric_rows, curve_rows = _build_paragraph_rows(chunks)
        paragraph_repo = ParagraphRepository(self.db_session)
        paragraph_repo.insert_paragraphs(self.run_id, spans)
        paragraph_repo.insert_paragraph_metrics(self.run_id, metric_rows)
        paragraph_repo.insert_paragraph_curves(self.run_id, curve_rows)

    @pytest.mark.asyncio()
    async def test_aggregate_basic(self) -> None:
        self._create_chunks_with_paragraphs(5)

        chunks, stats_count, reserved = await run_aggregate(run_id=self.run_id, session=self.db_session)
        assert chunks == 5
        assert stats_count > 0
        assert reserved == 0

        stats_count = self.db_session.execute(
            text("SELECT COUNT(*) FROM global_stats WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar()
        assert stats_count > 0

    @pytest.mark.asyncio()
    async def test_aggregate_global_stats(self) -> None:
        self._create_chunks_with_paragraphs(5)

        await run_aggregate(run_id=self.run_id, session=self.db_session)

        stats = self.db_session.execute(
            text("SELECT stat_name, stat_value FROM global_stats WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).fetchall()
        stat_names = [s[0] for s in stats]
        assert "global_avg_mtld" in stat_names
        assert "global_avg_ttr" in stat_names
        assert "global_avg_sent_len" in stat_names
        assert "emotion_avg" in stat_names
        assert "emotion_std" in stat_names
        assert "emotion_max" in stat_names
        assert "emotion_min" in stat_names
        assert "rhythm_avg" in stat_names
        assert "rhythm_std" in stat_names

        by_name = dict(stats)
        # §9.1 守恒：全书情绪密度 = (Σpos − Σneg) / Σtoken
        assert by_name["emotion_avg"] == pytest.approx((5 * 1.0 - 5 * 0.5) / (5 * 10))
        # 平均句长 = Σsentence_char_sum / Σsentence_count
        assert by_name["global_avg_sent_len"] == pytest.approx(40.0 / 2)
        # 章张力均值 = 段落 surface_tension 均值
        assert by_name["rhythm_avg"] == pytest.approx(sum(0.3 + i * 0.1 for i in range(5)) / 5)

    @pytest.mark.asyncio()
    async def test_aggregate_with_annotations(self) -> None:
        chunk_repo = ChunkRepository(self.db_session)
        texts = [f"测试文本{i}" for i in range(3)]
        test_chunks: list[Chunk] = []
        offset = 0
        for i, chunk_text in enumerate(texts):
            test_chunks.append(
                Chunk(index=i, start=offset, end=offset + len(chunk_text), text=chunk_text, chapter_id=i + 1)
            )
            offset += len(chunk_text)
        chunk_repo.insert_chunks(self.run_id, test_chunks)

        spans, metric_rows, curve_rows = _build_paragraph_rows(test_chunks)
        paragraph_repo = ParagraphRepository(self.db_session)
        paragraph_repo.insert_paragraphs(self.run_id, spans)
        paragraph_repo.insert_paragraph_metrics(self.run_id, metric_rows)
        paragraph_repo.insert_paragraph_curves(self.run_id, curve_rows)

        persist_chapter_annotation(
            self.db_session,
            run_id=self.run_id,
            chapter_id=1,
            emotional_valences={0: "strong_positive", 1: "mild_positive", 2: "mild_positive"},
            event_types={0: "冲突", 1: "铺垫", 2: "铺垫"},
            pivot_chunks={0},
            cliffhanger_chunks={2},
        )

        chunks, stats_count, _ = await run_aggregate(run_id=self.run_id, session=self.db_session)
        assert chunks == 3
        assert stats_count > 0

    @pytest.mark.asyncio()
    async def test_aggregate_empty_db(self) -> None:
        chunks, stats_count, _ = await run_aggregate(run_id=self.run_id, session=self.db_session)
        assert chunks == 0
        assert stats_count == 0

    @pytest.mark.asyncio()
    async def test_aggregate_metrics_graph_not_ready_degrades_gracefully(self, monkeypatch) -> None:
        """2026-08-13 P2-3 用于验证 aggregate_all_metrics 抛 GraphReadinessError 时
        保留降级（global_stats 正常写入）且记录 error 级别日志"""
        from unittest.mock import patch

        from src.api.exceptions import GraphReadinessError

        self._create_chunks_with_paragraphs(3)
        messages: list[str] = []

        def _capture(message: str) -> None:
            messages.append(str(message))

        monkeypatch.setattr("src.workflows.aggregate.logger.error", _capture)
        with patch(
            "src.workflows.aggregate.aggregate_all_metrics",
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
    跨 run 累积的数据会污染当前 run 的 global_avg_* 指标（M8b 后改为段落充分统计量聚合）。"""

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
        chunk_repo = ChunkRepository(self.db_session)
        chunk_text = "测试文本内容。"
        chunk_repo.insert_chunks(
            run_id,
            [Chunk(index=0, start=0, end=len(chunk_text), text=chunk_text, chapter_id=1)],
        )
        spans, metric_rows, curve_rows = _build_paragraph_rows(
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

    def test_global_stats_only_aggregates_own_run(self) -> None:
        from src.workflows.curve_metrics import compute_global_stats

        self._insert_metrics_for_run(self.run_a, sentence_sum=20.0, sentence_count=1)
        self._insert_metrics_for_run(self.run_b, sentence_sum=100.0, sentence_count=2)

        stats_a = dict(compute_global_stats(self.db_session, self.run_a))
        stats_b = dict(compute_global_stats(self.db_session, self.run_b))

        # run_b 的句长统计不得污染 run_a 的均值
        assert stats_a["global_avg_sent_len"] == pytest.approx(20.0)
        assert stats_b["global_avg_sent_len"] == pytest.approx(50.0)
        assert "global_avg_ttr" in stats_a
        assert "global_avg_mtld" in stats_a
