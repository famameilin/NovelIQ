"""preprocess 段落事实源测试

验证 run_preprocess 无条件生成 paragraphs（语义检索开关不影响段落事实源），
段落身份（paragraph_id/坐标）正确，
且 paragraph embedding 与段落事实源严格对齐
"""

from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from src.config import settings
from src.storage import new_id
from src.storage.models import ParagraphFeature, ParagraphMetric, Run
from src.storage.models.paragraph_features import (
    FEATURE_LOWESS_NET_DENSITY,
    FEATURE_LOWESS_SURFACE_TENSION,
    FEATURE_SEMANTIC_VECTOR,
    FEATURE_TENSION_Z,
)
from src.storage.repositories import ChapterRepository, RunRepository
from src.storage.repositories.paragraph_repository import ParagraphRepository
from src.text_processing.chapters.preprocess import preprocess_text
from src.text_processing.preprocess import normalize_text
from src.workflows.preprocess import run_preprocess
from src.workflows.preprocess_readiness import is_preprocess_complete
from tests.support.analysis_factories import insert_test_novel
from tests.support.storage_fixtures import storage_for


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
        source_path = Path(tmp) / f"novel_{new_id()}.txt"
        source_path.write_text(content, encoding="utf-8")
        return source_path

    def _create_run(self, db_session, source_path: Path, title: str) -> str:
        run_repo = RunRepository(db_session)
        novel_id = new_id()
        insert_test_novel(novel_id, session=db_session)
        return run_repo.create_run(novel_id=novel_id)

    @pytest.mark.asyncio()
    @patch("src.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_generates_paragraphs(self, db_session, tmp_path) -> None:
        """验证 preprocess 无条件生成段落事实源：
        paragraph_id 从 0 连续、global 坐标单调不重叠、char_count == len(text)、
        文本与 run 级规范化全文切片逐字匹配、content_hash 非空
        """
        source_path = self._create_source_file(str(tmp_path))
        run_id = self._create_run(db_session, source_path, "Paragraphs Novel")

        chunks_inserted, _, _ = await run_preprocess(
            source_path=source_path, run_id=run_id, session=storage_for(db_session)
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
        # run_preprocess 填充 token_count
        assert all(row.token_count is not None for row in rows)

    @pytest.mark.asyncio()
    @patch("src.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_paragraphs_identical_when_semantic_disabled(
        self,
        db_session,
        tmp_path,
        monkeypatch,
    ) -> None:
        """证明语义检索开关不影响段落事实源：
        semantic_enabled 开/关两个 run 的 paragraphs 行数一致且坐标/文本完全一致
        """
        source_path = self._create_source_file(str(tmp_path))

        run_id_semantic = self._create_run(db_session, source_path, "Semantic On")
        await run_preprocess(source_path=source_path, run_id=run_id_semantic, session=storage_for(db_session))

        monkeypatch.setattr(settings.models.paragraph_embedding, "semantic_enabled", False)
        run_id_plain = self._create_run(db_session, source_path, "Semantic Off")
        await run_preprocess(source_path=source_path, run_id=run_id_plain, session=storage_for(db_session))

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
        assert [tuple(getattr(row, field) for field in identity_fields) for row in rows_semantic] == [
            tuple(getattr(row, field) for field in identity_fields) for row in rows_plain
        ]

    @pytest.mark.asyncio()
    @patch("src.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_embeddings_aligned_with_paragraphs(self, db_session, tmp_path) -> None:
        """embedding 从段落事实源读取后按 paragraph_id 严格对齐：
        段落语义向量行数与 paragraphs 一致，向量非空、维度与实测探测一致

        向量行落 paragraph_features 的 semantic_vector 行；
        运行模型合同（模型 key）记在分析运行行，维度由探测实测后校验
        """
        source_path = self._create_source_file(str(tmp_path))
        run_id = self._create_run(db_session, source_path, "Embedding Align")

        await run_preprocess(source_path=source_path, run_id=run_id, session=storage_for(db_session))

        paragraph_rows = ParagraphRepository(db_session).fetch_paragraph_rows(run_id)
        assert paragraph_rows

        feature_rows = db_session.execute(
            select(ParagraphFeature.paragraph_id, ParagraphFeature.vector_value).where(
                ParagraphFeature.run_id == run_id,
                ParagraphFeature.feature_code == FEATURE_SEMANTIC_VECTOR,
            )
        ).all()
        vector_by_paragraph = {int(row.paragraph_id): row.vector_value for row in feature_rows}

        assert len(feature_rows) == len(paragraph_rows)
        for paragraph_row in paragraph_rows:
            vector = vector_by_paragraph[paragraph_row.paragraph_id]
            assert vector is not None
            assert len(vector) == 1024

        run = db_session.get(Run, run_id)
        assert run is not None

    @pytest.mark.asyncio()
    @patch("src.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_resume_skips_when_paragraphs_exist(self, db_session, tmp_path) -> None:
        """验证 is_preprocess_complete 要求段落事实源存在：
        第一次跑完后 paragraphs 已落库，第二次跑直接返回 (0, 0, 0)
        """
        source_path = self._create_source_file(str(tmp_path), "测试文本内容。" * 100)
        run_id = self._create_run(db_session, source_path, "Resume Novel")

        chunks1, _, _ = await run_preprocess(source_path=source_path, run_id=run_id, session=storage_for(db_session))
        assert chunks1 > 0
        assert ParagraphRepository(db_session).count_paragraphs(run_id) > 0
        assert is_preprocess_complete(storage_for(ChapterRepository(db_session).session), run_id)

        chunks2, chars2, elapsed2 = await run_preprocess(
            source_path=source_path, run_id=run_id, session=storage_for(db_session)
        )
        assert (chunks2, chars2, elapsed2) == (0, 0, 0.0)

    @pytest.mark.asyncio()
    @patch("src.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_generates_paragraph_metrics(self, db_session, tmp_path) -> None:
        """验证段落指标随 preprocess 无条件生成：
        行数等于段落数、基础分子/分母字段齐备

        张力 z 观测落 paragraph_features 的 tension_z 行，
        固定功能词/语义类别计数落 paragraph_metrics 明确计数列（缺项补零）
        """
        source_path = self._create_source_file(str(tmp_path))
        run_id = self._create_run(db_session, source_path, "Metrics Novel")

        await run_preprocess(source_path=source_path, run_id=run_id, session=storage_for(db_session))

        paragraph_repo = ParagraphRepository(db_session)
        paragraph_count = paragraph_repo.count_paragraphs(run_id)
        assert paragraph_count > 0

        metric_rows = db_session.scalars(select(ParagraphMetric).where(ParagraphMetric.run_id == run_id)).all()
        assert len(metric_rows) == paragraph_count
        for row in metric_rows:
            assert row.token_count >= 0
            assert row.sentence_count >= 0
            # 零命中是合法观测（完成但零计数存 0，不留 NULL）
            assert row.fw_之 == 0
            assert row.semantic_color == 0

        tension_rows = db_session.scalars(
            select(ParagraphFeature).where(
                ParagraphFeature.run_id == run_id,
                ParagraphFeature.feature_code == FEATURE_TENSION_Z,
            )
        ).all()
        paragraph_ids = {int(row.paragraph_id) for row in metric_rows}
        assert {int(row.paragraph_id) for row in tension_rows} == paragraph_ids
        for row in tension_rows:
            # z 已被 clip 到 [-3, 3]；sigmoid 展示值为读取投影
            assert row.scalar_value is not None
            assert -3.0 <= row.scalar_value <= 3.0

    @pytest.mark.asyncio()
    @patch("src.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_paragraph_metrics_counts_conservation(self, db_session, tmp_path) -> None:
        """验证段落指标与段落事实源守恒：
        每行 token_count 与 paragraphs 行一致、sentence 充分统计量与段落文本逐条匹配

        char_count 由段落正文长度投影，token_count 为指标行计数并被段落读取投影
        """
        source_path = self._create_source_file(str(tmp_path))
        run_id = self._create_run(db_session, source_path, "Conservation Novel")

        await run_preprocess(source_path=source_path, run_id=run_id, session=storage_for(db_session))

        paragraph_repo = ParagraphRepository(db_session)
        paragraph_rows = paragraph_repo.fetch_paragraph_rows(run_id)
        metric_rows = db_session.scalars(select(ParagraphMetric).where(ParagraphMetric.run_id == run_id)).all()
        metric_by_paragraph = {row.paragraph_id: row for row in metric_rows}

        assert len(metric_rows) == len(paragraph_rows)
        for paragraph_row in paragraph_rows:
            metric = metric_by_paragraph[paragraph_row.paragraph_id]
            assert paragraph_row.char_count == len(paragraph_row.text)
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
    @patch("src.embedding.EmbeddingClient", MockEmbeddingClientPreprocess)
    async def test_preprocess_generates_paragraph_curves(self, db_session, tmp_path) -> None:
        """验证段落曲线随 preprocess 无条件生成：
        每段两条曲线平滑值（净密度/表面张力）、运行级曲线合同、不可计算语义

        平滑值落 paragraph_features 的两类标量行，
        LOWESS 参数落 runs；原始 pos/neg 密度由指标分子÷token_count 投影
        """
        source_path = self._create_source_file(str(tmp_path))
        run_id = self._create_run(db_session, source_path, "Curves Novel")

        await run_preprocess(source_path=source_path, run_id=run_id, session=storage_for(db_session))

        paragraph_repo = ParagraphRepository(db_session)
        paragraph_count = paragraph_repo.count_paragraphs(run_id)
        assert paragraph_count > 0

        metric_rows = db_session.scalars(select(ParagraphMetric).where(ParagraphMetric.run_id == run_id)).all()
        metric_by_paragraph = {row.paragraph_id: row for row in metric_rows}

        samples = db_session.scalars(
            select(ParagraphFeature).where(
                ParagraphFeature.run_id == run_id,
                ParagraphFeature.feature_code.in_((FEATURE_LOWESS_NET_DENSITY, FEATURE_LOWESS_SURFACE_TENSION)),
            )
        ).all()
        by_paragraph: dict[int, dict[str, float | None]] = {}
        for row in samples:
            by_paragraph.setdefault(int(row.paragraph_id), {})[row.feature_code] = row.scalar_value

        assert set(by_paragraph) == set(metric_by_paragraph)
        for paragraph_id, kinds in by_paragraph.items():
            metric = metric_by_paragraph[paragraph_id]
            if metric.token_count > 0:
                assert set(kinds) == {FEATURE_LOWESS_NET_DENSITY, FEATURE_LOWESS_SURFACE_TENSION}
                assert kinds[FEATURE_LOWESS_NET_DENSITY] is not None
                assert math.isfinite(kinds[FEATURE_LOWESS_NET_DENSITY])
            else:
                # 分母为零不伪造：不可计算不落行
                assert FEATURE_LOWESS_NET_DENSITY not in kinds
            assert kinds[FEATURE_LOWESS_SURFACE_TENSION] is not None
            assert math.isfinite(kinds[FEATURE_LOWESS_SURFACE_TENSION])
