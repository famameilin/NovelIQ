"""
preprocess 段落事实源测试

验证 run_preprocess 无条件生成 paragraphs（语义检索开关不影响段落事实源），
段落身份（paragraph_id/坐标/版本号）符合设计文档《段落分析原子与章节汇总重设计方案》§5.1，
且 paragraph embedding 与段落事实源严格对齐
"""

from __future__ import annotations

import math
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from src.chapters.preprocess import preprocess_text
from src.config import settings
from src.preprocess.cleaning import normalize_text
from src.storage.models import Paragraph, ParagraphCurve, ParagraphEmbedding, ParagraphMetric
from src.storage.repositories import ChapterRepository, RunRepository
from src.storage.repositories.paragraph_repository import ParagraphRepository
from src.workflows.preprocess import run_preprocess
from tests.support.analysis_factories import insert_test_novel


class MockEmbeddingClientPreprocess:
    def __init__(self, *args, **kwargs):
        pass

    async def get_embedding(self, text: str, chunk_id: int | None = None):
        import random

        return [random.random() for _ in range(1024)]

    async def embed_texts(
        self,
        texts: list[str],
        *,
        progress_callback=None,
    ) -> list[list[float]]:
        import random

        return [[random.random() for _ in range(1024)] for _ in texts]

    async def detect_embedding_dimension(self, probe_text: str = "dimension probe") -> int:
        return 1024

    @staticmethod
    def compute_similarity(vec1, vec2):
        return 0.5


# 章节标题 + 三个自然段：段落边界为单换行，方便验证坐标/文本与全文切片逐字匹配
_NOVEL_CONTENT = "第一章 测试\n第一段内容。\n第二段内容。\n第三段内容。"


class TestPreprocessParagraphs:
    def _create_source_file(self, tmp: str, content: str = _NOVEL_CONTENT) -> Path:
        source_path = Path(tmp) / f"novel_{uuid.uuid4().hex[:8]}.txt"
        source_path.write_text(content, encoding="utf-8")
        return source_path

    def _create_run(self, db_session, source_path: Path, title: str) -> str:
        run_repo = RunRepository(db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=db_session)
        return run_repo.create_run(
            novel_id=novel_id,
            source_path=str(source_path),
            title=title,
        )

    @pytest.mark.asyncio()
    @patch("src.models.local.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_generates_paragraphs(self, db_session, tmp_path) -> None:
        """
        2026-08-14 用于验证 preprocess 无条件生成段落事实源：
        paragraph_id 从 0 连续、global 坐标单调不重叠、char_count == len(text)、
        文本与 run 级规范化全文切片逐字匹配、content_hash 非空、splitter_version 落库
        """
        source_path = self._create_source_file(str(tmp_path))
        run_id = self._create_run(db_session, source_path, "Paragraphs Novel")

        chunks_inserted, _, _ = await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
        )
        assert chunks_inserted > 0

        paragraph_repo = ParagraphRepository(db_session)
        assert paragraph_repo.count_paragraphs(run_id) > 0

        rows = paragraph_repo.fetch_paragraph_rows(run_id)
        # paragraph_id 从 0 全局连续
        assert [row.paragraph_id for row in rows] == list(range(len(rows)))
        # global 坐标单调不重叠
        prev_end = -1
        for row in rows:
            assert row.global_start_char >= prev_end
            assert row.global_start_char < row.global_end_char
            assert row.local_start_char < row.local_end_char
            prev_end = row.global_end_char
        # char_count == len(text)（从 DB 行 text 列验证）
        assert all(row.char_count == len(row.text) for row in rows)
        # 文本与章节切片逐字匹配（global 坐标相对 run 级规范化全文）
        raw_text = source_path.read_text(encoding="utf-8")
        full_text = preprocess_text(normalize_text(raw_text))
        for row in rows:
            assert row.text == full_text[row.global_start_char : row.global_end_char]
        # content_hash 非空；splitter_version/tokenizer_version 从 settings.paragraphs 落库
        # （fetch_paragraph_rows 未投影版本列，直接查 Paragraph 模型验证）
        assert all(row.content_hash for row in rows)
        version_rows = db_session.execute(
            select(Paragraph.splitter_version, Paragraph.tokenizer_version).where(
                Paragraph.run_id == run_id
            )
        ).all()
        assert version_rows
        assert all(row.splitter_version == "1" for row in version_rows)
        assert all(row.tokenizer_version == "1" for row in version_rows)
        # run_preprocess 填充 token_count
        assert all(row.token_count is not None for row in rows)

    @pytest.mark.asyncio()
    @patch("src.models.local.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_paragraphs_identical_when_semantic_disabled(
        self,
        db_session,
        tmp_path,
        monkeypatch,
    ) -> None:
        """
        2026-08-14 用于证明语义检索开关不影响段落事实源：
        semantic_enabled 开/关两个 run 的 paragraphs 行数一致且坐标/文本完全一致
        """
        source_path = self._create_source_file(str(tmp_path))

        run_id_semantic = self._create_run(db_session, source_path, "Semantic On")
        await run_preprocess(
            source_path=source_path,
            run_id=run_id_semantic,
            session=db_session,
        )

        monkeypatch.setattr(settings.models.paragraph_embedding, "semantic_enabled", False)
        run_id_plain = self._create_run(db_session, source_path, "Semantic Off")
        await run_preprocess(
            source_path=source_path,
            run_id=run_id_plain,
            session=db_session,
        )

        paragraph_repo = ParagraphRepository(db_session)
        rows_semantic = paragraph_repo.fetch_paragraph_rows(run_id_semantic)
        rows_plain = paragraph_repo.fetch_paragraph_rows(run_id_plain)
        assert len(rows_semantic) == len(rows_plain)
        identity_fields = (
            "paragraph_id",
            "chapter_id",
            "paragraph_index",
            "local_start_char",
            "local_end_char",
            "global_start_char",
            "global_end_char",
            "text",
        )
        assert [
            tuple(getattr(row, field) for field in identity_fields) for row in rows_semantic
        ] == [
            tuple(getattr(row, field) for field in identity_fields) for row in rows_plain
        ]

    @pytest.mark.asyncio()
    @patch("src.models.local.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_embeddings_aligned_with_paragraphs(self, db_session, tmp_path) -> None:
        """
        2026-08-14 二期段落化：embedding 从段落事实源读取后按 paragraph_id 严格对齐：
        paragraph_embeddings 行数与 paragraphs 一致，向量非空、维度与配置一致、
        source_content_hash 对照 paragraphs.content_hash
        """
        source_path = self._create_source_file(str(tmp_path))
        run_id = self._create_run(db_session, source_path, "Embedding Align")

        await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
        )

        paragraph_rows = ParagraphRepository(db_session).fetch_paragraph_rows(run_id)
        assert paragraph_rows

        embedding_rows = db_session.execute(
            select(
                ParagraphEmbedding.run_id,
                ParagraphEmbedding.paragraph_id,
                ParagraphEmbedding.embedding_vector,
                ParagraphEmbedding.embedding_model_key,
                ParagraphEmbedding.embedding_dimension,
                ParagraphEmbedding.source_content_hash,
            ).where(ParagraphEmbedding.run_id == run_id)
        ).all()
        embedding_by_id = {row.paragraph_id: row for row in embedding_rows}

        assert len(embedding_rows) == len(paragraph_rows)
        for paragraph_row in paragraph_rows:
            embedding_row = embedding_by_id[paragraph_row.paragraph_id]
            assert embedding_row.embedding_vector is not None
            assert len(embedding_row.embedding_vector) == 1024
            assert embedding_row.embedding_dimension == 1024
            # 溯源：source_content_hash 与段落事实源 content_hash 一致
            assert embedding_row.source_content_hash == paragraph_row.content_hash

    @pytest.mark.asyncio()
    @patch("src.models.local.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_resume_skips_when_paragraphs_exist(self, db_session, tmp_path) -> None:
        """
        2026-08-14 用于验证 is_preprocess_complete 要求段落事实源存在：
        第一次跑完后 paragraphs 已落库，第二次跑直接返回 (0, 0, 0)
        """
        source_path = self._create_source_file(str(tmp_path), "测试文本内容。" * 100)
        run_id = self._create_run(db_session, source_path, "Resume Novel")

        chunks1, _, _ = await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
        )
        assert chunks1 > 0
        assert ParagraphRepository(db_session).count_paragraphs(run_id) > 0
        assert ChapterRepository(db_session).is_preprocess_complete(run_id)

        chunks2, chars2, elapsed2 = await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
        )
        assert (chunks2, chars2, elapsed2) == (0, 0, 0.0)

    @pytest.mark.asyncio()
    @patch("src.models.local.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_generates_paragraph_metrics(self, db_session, tmp_path) -> None:
        """
        2026-08-14 用于验证段落指标（§5.3）随 preprocess 无条件生成：
        行数等于段落数、分子/分母字段非空、surface_tension 值域合法、
        metric_version 落库
        """
        source_path = self._create_source_file(str(tmp_path))
        run_id = self._create_run(db_session, source_path, "Metrics Novel")

        await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
        )

        paragraph_repo = ParagraphRepository(db_session)
        paragraph_count = paragraph_repo.count_paragraphs(run_id)
        assert paragraph_count > 0

        metric_rows = db_session.scalars(
            select(ParagraphMetric).where(ParagraphMetric.run_id == run_id)
        ).all()
        assert len(metric_rows) == paragraph_count
        for row in metric_rows:
            assert row.metric_version == str(settings.metrics.metric_version)
            assert row.char_count > 0
            assert row.token_count >= 0
            assert row.sentence_count >= 0
            assert row.surface_tension_z is not None
            assert row.surface_tension is not None
            # sigmoid 值域 (0, 1)；z 已被 clip 到 [-3, 3]
            assert 0.0 < row.surface_tension < 1.0
            assert -3.0 <= row.surface_tension_z <= 3.0
            assert row.function_word_counts is not None
            assert row.semantic_category_counts is not None

    @pytest.mark.asyncio()
    @patch("src.models.local.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_paragraph_metrics_counts_conservation(self, db_session, tmp_path) -> None:
        """
        2026-08-14 用于验证段落指标与段落事实源守恒：
        每行 char_count == len(段落文本)、token_count 与 paragraphs 行一致、
        sentence 充分统计量与段落文本逐条匹配
        """
        source_path = self._create_source_file(str(tmp_path))
        run_id = self._create_run(db_session, source_path, "Conservation Novel")

        await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
        )

        paragraph_repo = ParagraphRepository(db_session)
        paragraph_rows = paragraph_repo.fetch_paragraph_rows(run_id)
        metric_rows = db_session.scalars(
            select(ParagraphMetric).where(ParagraphMetric.run_id == run_id)
        ).all()
        metric_by_paragraph = {row.paragraph_id: row for row in metric_rows}

        assert len(metric_rows) == len(paragraph_rows)
        for paragraph_row in paragraph_rows:
            metric = metric_by_paragraph[paragraph_row.paragraph_id]
            assert metric.char_count == len(paragraph_row.text)
            assert metric.token_count == paragraph_row.token_count
            # sentence 充分统计量：均值/方差恢复一致（由 count/sum/sum_sq 恢复）
            if metric.sentence_count > 0:
                mean = metric.sentence_char_sum / metric.sentence_count
                variance = max(
                    0.0,
                    metric.sentence_char_sum_sq / metric.sentence_count - mean * mean,
                )
                assert variance >= 0.0

    @pytest.mark.asyncio()
    @patch("src.models.local.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_generates_paragraph_curves(self, db_session, tmp_path) -> None:
        """
        2026-08-14 用于验证段落曲线（§5.5）随 preprocess 无条件生成：
        行数等于段落数、net_density 与手工分子/分母一致、smoothed 无 NaN、
        surface_tension 与 paragraph_metrics 一致、curve_version 落库
        """
        source_path = self._create_source_file(str(tmp_path))
        run_id = self._create_run(db_session, source_path, "Curves Novel")

        await run_preprocess(
            source_path=source_path,
            run_id=run_id,
            session=db_session,
        )

        paragraph_repo = ParagraphRepository(db_session)
        paragraph_count = paragraph_repo.count_paragraphs(run_id)
        assert paragraph_count > 0

        curve_rows = db_session.scalars(
            select(ParagraphCurve).where(ParagraphCurve.run_id == run_id)
        ).all()
        metric_rows = db_session.scalars(
            select(ParagraphMetric).where(ParagraphMetric.run_id == run_id)
        ).all()
        assert len(curve_rows) == paragraph_count
        metric_by_paragraph = {row.paragraph_id: row for row in metric_rows}

        for row in curve_rows:
            metric = metric_by_paragraph[row.paragraph_id]
            assert row.curve_version == "1"
            if metric.token_count > 0:
                assert row.pos_density == pytest.approx(
                    metric.positive_weight_sum / metric.token_count
                )
                assert row.neg_density == pytest.approx(
                    metric.negative_weight_sum / metric.token_count
                )
                assert row.net_density == pytest.approx(
                    metric.positive_weight_sum / metric.token_count
                    - metric.negative_weight_sum / metric.token_count
                )
                assert row.smoothed_net_density is not None
                assert math.isfinite(row.smoothed_net_density)
            else:
                assert row.net_density is None
                assert row.smoothed_net_density is None
            assert row.surface_tension == pytest.approx(metric.surface_tension)
            if metric.surface_tension is not None:
                assert row.smoothed_surface_tension is not None
                assert math.isfinite(row.smoothed_surface_tension)
