"""语言结构阶段集成测试（run_linguistic，§3.1 B/C 赛道）

LTP 推理用 FakeLtpSession 替换（真实 LTP 模型只做模块级验证），
analyze_paragraph 纯函数路径保持真实；短语匹配与 Word2Vec 全真实。
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Row

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.chunking.chunker import Chunk, split_chunk_paragraphs
from src.linguistic.ltp_client import LtpPipelineOutput
from src.storage.repositories import ChapterRepository, ParagraphRepository, RunRepository
from src.storage.repositories.linguistic_repository import LinguisticRepository
from src.workflows.linguistic import run_linguistic
from tests.support.analysis_factories import insert_test_novel

_TEST_TEXTS = ["江湖快意恩仇，刀光剑影之间英雄辈出。", "他叫汤姆去拿外衣，但是天色已晚。"]


class FakeLtpSession:
    """按句返回与 LTP 同构的输出（每字符一词、简单树形依存）"""

    def pipeline(self, sentences, tasks):
        cws: list[list[str]] = []
        pos: list[list[str]] = []
        ner: list[list[tuple[str, str, int, int]]] = []
        dep: list[dict[str, list]] = []
        for sentence in sentences:
            words = list(self._WORDS) if "高兴" in sentence else list(sentence)
            cws.append(words)
            pos.append(["n" if w != "，" and w != "。" else "wp" for w in words])
            dep.append({"head": [0] * len(words), "label": ["HED"] * len(words)})
            ner.append([("Nh", "汤姆", 2, 2)] if "汤姆" in sentence else [])
        return LtpPipelineOutput(cws=cws, pos=pos, ner=ner, dep=dep)


class TestRunLinguistic:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, monkeypatch):
        self.db_session = db_session
        self.novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(self.novel_id, session=db_session)
        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

        chapters = [
            Chunk(index=i, start=i * 100, end=i * 100 + len(text), text=text, chapter_id=i + 1)
            for i, text in enumerate(_TEST_TEXTS)
        ]
        ChapterRepository(db_session).insert_chapter_texts(self.run_id, chapters)
        spans = [replace(span, token_count=2) for span in split_chunk_paragraphs(chapters)]
        ParagraphRepository(db_session).insert_paragraphs(self.run_id, spans)

        from src.linguistic import ltp_client

        monkeypatch.setattr(ltp_client.LtpSession, "get_instance", lambda: FakeLtpSession())

        # 隔离真实 settings：默认关词向量，防止 settings.json 开启 pretrained 时
        # 测试内加载 4.5GB 预训练文件；词向量用例自行 monkeypatch 开启
        from src.config import settings as _settings

        monkeypatch.setattr(_settings.linguistic.word2vec, "enabled", False)

        # draft 审定门验证：draft 文件经 2026-09-07 审定后为空，注入非空 draft
        # 词条保持"draft 命中不计入正式密度"的门路径始终被测试覆盖
        from src.config.constants import LEXICON_FILES
        from src.lexicons.registry import LexiconRegistry

        self._draft_key = LEXICON_FILES["body_reaction_draft"]
        _orig_reg_get = LexiconRegistry.get

        def _reg_get_with_injected_draft(self_: LexiconRegistry, key: str) -> list[str]:
            if key == self._draft_key:
                return ["外衣"]
            return _orig_reg_get(self_, key)

        monkeypatch.setattr(LexiconRegistry, "get", _reg_get_with_injected_draft)

    def _count(self, table: str) -> int:
        return int(
            self.db_session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE run_id = :run_id"),
                {"run_id": self.run_id},
            ).scalar()
            or 0
        )

    def _feature_rows(self) -> list[Row]:
        return LinguisticRepository(self.db_session).fetch_linguistic_features(self.run_id)

    @pytest.mark.asyncio()
    async def test_runs_all_steps_and_writes_three_tables(self) -> None:
        paragraphs, features = await run_linguistic(self.run_id, self.db_session)
        assert paragraphs == 2
        assert features == 2

        assert self._count("paragraph_linguistic_features") == 2
        assert self._count("paragraph_entities") > 0  # 汤姆 Nh person
        assert self._count("paragraph_phrase_hits") > 0  # 快意恩仇/刀光剑影命中

        # draft 词表命中与四字候选都不计入正式密度
        phrase_rows = LinguisticRepository(self.db_session).fetch_phrase_hits(self.run_id)
        lexicon_rows = [row for row in phrase_rows if row.match_kind == "lexicon"]
        assert lexicon_rows and all(not row.is_metric_hit for row in lexicon_rows)
        # 注入的 draft 词条命中留痕（外衣不在任何正式表，只能来自 draft 门）
        draft_rows = [row for row in lexicon_rows if row.surface_text == "外衣"]
        assert draft_rows and all(not row.is_metric_hit for row in draft_rows)
        candidate_rows = [row for row in phrase_rows if row.match_kind == "four_char_candidate"]
        assert all(not row.is_metric_hit for row in candidate_rows)

        rows = self._feature_rows()
        assert len(rows) == 2
        assert all(row.paragraph_id in (0, 1) for row in rows)

    @pytest.mark.asyncio()
    async def test_word2vec_enabled_trains_and_writes_contract(self, monkeypatch, tmp_path) -> None:
        """2026-08-30 用于验证共享 kv 初始化后写入实际来源与 run 私有模型契约"""

        from src.config import settings as _settings
        from src.linguistic import reset_pretrained_cache

        reset_pretrained_cache()

        # 极小预训练词向量文件（dim=4，含书内词元"江/湖/刀/剑"供微调命中），转成 .kv
        fixture = tmp_path / "fixture.vec"
        rows = ["4 4"]
        for i, word in enumerate(["江", "湖", "刀", "剑"]):
            rows.append(f"{word} " + " ".join(f"{(i + j) / 10:.1f}" for j in range(4)))
        fixture.write_text("\n".join(rows) + "\n", encoding="utf-8")

        from gensim.models import KeyedVectors

        vectors = KeyedVectors.load_word2vec_format(str(fixture), binary=False)
        kv_path = tmp_path / "fixture.kv"
        vectors.save(str(kv_path))

        w2v = _settings.linguistic.word2vec
        monkeypatch.setattr(w2v, "enabled", True)
        monkeypatch.setattr(w2v, "model_dir", str(tmp_path))
        monkeypatch.setattr(w2v, "min_count", 1)
        monkeypatch.setattr(w2v, "epochs", 1)

        run_model_dir = tmp_path / "run-models" / self.run_id

        def resolve_test_run_model_dir(candidate_run_id: str, kind: str) -> Path:
            """2026-08-30 用于把工作流 run 模型路径隔离到临时目录"""
            assert candidate_run_id == self.run_id
            assert kind == "word2vec"
            return run_model_dir

        monkeypatch.setattr(
            "src.storage.path_resolver.resolve_run_model_dir",
            resolve_test_run_model_dir,
        )

        try:
            paragraphs, features = await run_linguistic(self.run_id, self.db_session)
        finally:
            reset_pretrained_cache()
        assert paragraphs == 2
        assert features == 2

        model_run = LinguisticRepository(self.db_session).fetch_word2vec_model_run(self.run_id)
        assert model_run is not None
        assert model_run.embedding_dimension == 4
        assert model_run.artifact_scope == "run_owned"
        assert model_run.artifact_key == f"models/word2vec/{self.run_id}/word2vec.model"
        assert Path(model_run.source_uri) == kv_path.resolve()
        assert (run_model_dir / "word2vec.model").is_file()
        assert self._count("paragraph_pos_embeddings") > 0

    @pytest.mark.asyncio()
    async def test_rerun_clears_and_reinserts(self) -> None:
        await run_linguistic(self.run_id, self.db_session)
        first_features = self._count("paragraph_linguistic_features")
        first_hits = self._count("paragraph_phrase_hits")

        await run_linguistic(self.run_id, self.db_session)
        assert self._count("paragraph_linguistic_features") == first_features
        assert self._count("paragraph_phrase_hits") == first_hits
        assert self._count("paragraph_entities") >= 0

    @pytest.mark.asyncio()
    async def test_ltp_disabled_skips_all_linguistic_steps(self, monkeypatch) -> None:
        """LTP 关闭 → 无词法特征行；短语表依赖词法 FK（§5.5），一并跳过"""
        from src.config import settings as _settings

        monkeypatch.setattr(_settings.linguistic.ltp, "enabled", False)
        paragraphs, features = await run_linguistic(self.run_id, self.db_session)
        assert paragraphs == 2
        assert features == 0
        assert self._count("paragraph_linguistic_features") == 0
        assert self._count("paragraph_phrase_hits") == 0

    @pytest.mark.asyncio()
    async def test_batch_size_one_produces_same_rows_as_full_batch(self) -> None:
        """分批落库与一次全量落库结果一致（clear_first 只在首批生效，后续批追加）"""
        await run_linguistic(self.run_id, self.db_session, batch_size=1)
        batched_features = self._count("paragraph_linguistic_features")
        batched_entities = self._count("paragraph_entities")
        batched_phrases = self._count("paragraph_phrase_hits")

        # 清空后按默认大 batch 重跑，验证完全一致
        await run_linguistic(self.run_id, self.db_session)
        assert self._count("paragraph_linguistic_features") == batched_features
        assert self._count("paragraph_entities") == batched_entities
        assert self._count("paragraph_phrase_hits") == batched_phrases
        assert batched_features == 2

    @pytest.mark.asyncio()
    async def test_empty_run_returns_zero(self) -> None:
        run_repo = RunRepository(self.db_session)
        novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(novel_id, session=self.db_session)
        empty_run = run_repo.create_run(novel_id=novel_id, source_path="test", title="Empty")
        paragraphs, features = await run_linguistic(empty_run, self.db_session)
        assert paragraphs == 0
        assert features == 0


class FakeSdpLtpSession:
    """带 sdp 输出的 Fake：对"高兴"谓词注入 mNEG 弧（模型习得否定辖域）"""

    _WORDS = ("他", "很", "高兴")

    def pipeline(self, sentences, tasks):
        cws: list[list[str]] = []
        pos: list[list[str]] = []
        ner: list[list[tuple[str, str, int, int]]] = []
        dep: list[dict[str, list]] = []
        sdp: list[dict[str, list]] = []
        for sentence in sentences:
            words = list(self._WORDS) if "高兴" in sentence else list(sentence)
            cws.append(words)
            pos.append(["n"] * len(words))
            dep.append({"head": [0] * len(words), "label": ["HED"] * len(words)})
            ner.append([])
            heads: list[int] = []
            dependents: list[int] = []
            labels: list[str] = []
            for idx, word in enumerate(words, start=1):
                if word == "高兴":
                    # mNEG 弧：高兴(head=3) ←句首词元——fake 用句首词元充当否定词
                    heads.append(idx)
                    dependents.append(1)
                    labels.append("mNEG")
            sdp.append({"head": heads, "dependent": dependents, "label": labels})
        return LtpPipelineOutput(cws=cws, pos=pos, ner=ner, dep=dep, sdp=sdp)


class TestMnegCorrection:
    """2026-09-05 B 批：mNEG 接管词典否定翻转——paragraph_metrics 回写 + 曲线重算"""

    @pytest.fixture(autouse=True)
    def setup(self, db_session, monkeypatch):
        self.db_session = db_session
        self.novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(self.novel_id, session=db_session)
        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Mneg Novel")

        text = "他很高兴"
        chapters = [Chunk(index=0, start=0, end=len(text), text=text, chapter_id=1)]
        ChapterRepository(db_session).insert_chapter_texts(self.run_id, chapters)
        spans = [replace(span, token_count=4) for span in split_chunk_paragraphs(chapters)]
        paragraph_repo = ParagraphRepository(db_session)
        paragraph_repo.insert_paragraphs(self.run_id, spans)

        from src.linguistic import ltp_client

        monkeypatch.setattr(ltp_client.LtpSession, "get_instance", lambda: FakeSdpLtpSession())
        from src.config import settings as _settings

        monkeypatch.setattr(_settings.linguistic.word2vec, "enabled", False)

        # 预置窗口规则口径的情绪计数（模拟 preprocess 产物：未翻转 → 正 1 负 0）
        from src.storage.repositories.paragraph_repository import ParagraphMetricRow

        paragraph_repo.insert_paragraph_metrics(
            self.run_id,
            [
                ParagraphMetricRow(
                    paragraph_id=spans[0].paragraph_id,
                    token_count=4,
                    char_count=spans[0].char_count,
                    sentence_count=1,
                    sentence_char_sum=4.0,
                    sentence_char_sum_sq=16.0,
                    positive_weight_sum=1.0,
                    negative_weight_sum=0.0,
                    fight_weight_sum=0.0,
                    exclaim_count=0,
                    question_count=0,
                    pause_count=0,
                    dialogue_char_count=0,
                    sensory_hit_count=0,
                    imagery_hit_count=0,
                    metaphor_sentence_count=0,
                    body_reaction_hit_count=0,
                    function_word_counts={},
                    semantic_category_counts={},
                )
            ],
        )

    @pytest.mark.asyncio()
    async def test_mneg_flip_rewrites_metrics_and_stores_comparison(self) -> None:
        paragraphs, features = await run_linguistic(self.run_id, self.db_session)
        assert (paragraphs, features) == (1, 1)

        metric_row = self.db_session.execute(
            text(
                "SELECT positive_weight_sum, negative_weight_sum FROM paragraph_metrics "
                "WHERE run_id = :run_id AND paragraph_id = 0"
            ),
            {"run_id": self.run_id},
        ).one()
        # sdp mNEG 把"高兴"翻转为负：正 1→0、负 0→1
        assert float(metric_row.positive_weight_sum) == 0.0
        assert float(metric_row.negative_weight_sum) == 1.0

        feature = LinguisticRepository(self.db_session).fetch_linguistic_features(self.run_id)[0]
        assert float(feature.lexicon_pos_count) == 1.0
        assert float(feature.mneg_neg_count) == 1.0
        assert feature.emotion_event_count == 1
        event = feature.emotion_events[0]
        assert event["predicate"] == "高兴"
        assert event["negated"] is True
        assert event["holder"] is None

        # 曲线按修正分子重算：net_density = (0 - 1) / 4
        curve_row = self.db_session.execute(
            text(
                "SELECT net_density FROM paragraph_curves WHERE run_id = :run_id AND paragraph_id = 0"
            ),
            {"run_id": self.run_id},
        ).one()
        assert float(curve_row.net_density) == -0.25


class _EmbeddingFakeLtpSession(FakeLtpSession):
    """2026-09-07 用于句级监督测试：按情绪关键词返回可分句向量"""

    def sentence_embeddings(self, sentences):
        import numpy as np

        vectors = []
        for sentence in sentences:
            vector = np.zeros(4, dtype=np.float32)
            if "江湖" in sentence:
                vector[0] = 1.0
            elif "汤姆" in sentence:
                vector[0] = -1.0
            else:
                vector[1] = 0.5
            vectors.append(vector)
        return np.array(vectors, dtype=np.float32)


class TestParagraphBoundary:
    """2026-09-14 段落级监督（按书边界）：自选段标签→段落向量边界→逐段打分回写"""

    @pytest.fixture(autouse=True)
    def setup(self, db_session, monkeypatch):
        self.db_session = db_session
        self.novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(self.novel_id, session=db_session)
        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Boundary Novel")

        chapters = [
            Chunk(index=i, start=i * 100, end=i * 100 + len(text), text=text, chapter_id=i + 1)
            for i, text in enumerate(_TEST_TEXTS)
        ]
        ChapterRepository(db_session).insert_chapter_texts(self.run_id, chapters)
        spans = [replace(span, token_count=2) for span in split_chunk_paragraphs(chapters)]
        ParagraphRepository(db_session).insert_paragraphs(self.run_id, spans)

        # paragraph_embeddings 不在 init_db（preprocess 期才建表，列宽按实测维度固化）：
        # 本类自造向量样本，先按 4 维建表；teardown 恢复原状——ensure 只比对列集合、
        # 不比对维度，留下窄表会让用 1024 维的其他套件静默插库失败
        from sqlalchemy import text as sa_text

        from src.storage.vector_schema import _runtime_schema, ensure_paragraph_embeddings_schema

        runtime_schema = _runtime_schema()
        db_session.execute(sa_text(f"DROP TABLE IF EXISTS {runtime_schema}.paragraph_embeddings CASCADE"))
        ensure_paragraph_embeddings_schema(db_session, embedding_dim=4)

        from src.config import settings as _settings

        monkeypatch.setattr(_settings.linguistic.word2vec, "enabled", False)
        yield
        db_session.execute(sa_text(f"DROP TABLE IF EXISTS {runtime_schema}.paragraph_embeddings CASCADE"))

    def _feature_rows(self) -> list:
        return LinguisticRepository(self.db_session).fetch_linguistic_features(self.run_id)

    def _insert_annotation_with_labels(self, chapter_id: int, labels: list[dict]) -> None:
        from src.agents.annotation.schema import (
            BoundChapterAnnotation,
            BoundChunkAnnotation,
            BoundParagraphLabel,
            ChunkMetricsInput,
            NarrativeFunction,
        )
        from src.storage.repositories import ChapterAnnotationRepository

        annotation = BoundChapterAnnotation(
            chapter_summary="测试章节",
            chunks=[
                BoundChunkAnnotation(
                    chunk_id=chapter_id,
                    metrics=ChunkMetricsInput(
                        summary="测试",
                        emotional_valence=0,
                        narrative_function=NarrativeFunction.SETUP,
                    ),
                    character_observations=[],
                    dialogues=[],
                    events=[],
                    paragraph_labels=[BoundParagraphLabel(**label) for label in labels],
                )
            ],
        )
        ChapterAnnotationRepository(self.db_session).add_annotation(
            run_id=self.run_id,
            chapter_id=chapter_id,
            annotation=annotation,
        )

    def _insert_paragraph_embeddings(self, vectors_by_id: dict[int, list[float]]) -> None:
        from src.storage.models import ParagraphEmbedding

        for paragraph_id, vector in vectors_by_id.items():
            self.db_session.add(
                ParagraphEmbedding(
                    run_id=self.run_id,
                    paragraph_id=paragraph_id,
                    embedding_vector=vector,
                    embedding_model_key="test-fake",
                    embedding_dimension=len(vector),
                )
            )
        self.db_session.flush()

    @pytest.mark.asyncio()
    async def test_no_labels_keeps_boundary_columns_null(self) -> None:
        """无标签 run：两列 NULL，段落曲线维持 mNEG 口径"""
        await run_linguistic(self.run_id, self.db_session)
        rows = self._feature_rows()
        assert len(rows) == 2
        assert all(row.boundary_pos_score_sum is None for row in rows)
        assert all(row.boundary_neg_score_sum is None for row in rows)

    @pytest.mark.asyncio()
    async def test_labels_fit_boundary_and_fill_scores(self) -> None:
        """标签齐全：边界拟合成功，两列为段落自身边界分值（正段正和>0，负段负和>0）"""
        positive_id = next(i for i, text in enumerate(_TEST_TEXTS) if "江湖" in text)
        negative_id = next(i for i, text in enumerate(_TEST_TEXTS) if "汤姆" in text)
        self._insert_paragraph_embeddings(
            {
                positive_id: [1.0, 0.0, 0.0, 0.0],
                negative_id: [-1.0, 0.0, 0.0, 0.0],
            }
        )
        self._insert_annotation_with_labels(
            1,
            [
                {"paragraph_id": positive_id, "emotion": 2},
                {"paragraph_id": negative_id, "emotion": -2},
            ],
        )
        await run_linguistic(self.run_id, self.db_session)

        rows = {row.paragraph_id: row for row in self._feature_rows()}
        assert set(rows) == {0, 1}
        assert (rows[positive_id].boundary_pos_score_sum or 0) > 0
        assert rows[positive_id].boundary_neg_score_sum == pytest.approx(0.0, abs=1e-6)
        assert (rows[negative_id].boundary_neg_score_sum or 0) > 0
        assert rows[negative_id].boundary_pos_score_sum == pytest.approx(0.0, abs=1e-6)

    @pytest.mark.asyncio()
    async def test_labels_without_vectors_skip_boundary(self) -> None:
        """标签能对上段落向量的不足 2 条：不拟合边界，两列维持 NULL 不伪造"""
        positive_id = next(i for i, text in enumerate(_TEST_TEXTS) if "江湖" in text)
        negative_id = next(i for i, text in enumerate(_TEST_TEXTS) if "汤姆" in text)
        self._insert_paragraph_embeddings({positive_id: [1.0, 0.0, 0.0, 0.0]})
        self._insert_annotation_with_labels(
            1,
            [
                {"paragraph_id": positive_id, "emotion": 2},
                # 第二标签指向无向量的段落：fit 只用能对上向量的样本
                {"paragraph_id": negative_id, "emotion": -2},
            ],
        )
        await run_linguistic(self.run_id, self.db_session)
        rows = {row.paragraph_id: row for row in self._feature_rows()}
        # 仅 1 条标签能对上向量（<2）→ 不拟合边界，两列维持 NULL
        assert all(row.boundary_pos_score_sum is None for row in rows.values())

    @pytest.mark.asyncio()
    async def test_single_class_labels_skip_boundary(self) -> None:
        """标签全同分值（无类别差异）：边界不拟合，两列 NULL 不伪造"""
        positive_id = next(i for i, text in enumerate(_TEST_TEXTS) if "江湖" in text)
        negative_id = next(i for i, text in enumerate(_TEST_TEXTS) if "汤姆" in text)
        self._insert_paragraph_embeddings(
            {
                positive_id: [1.0, 0.0, 0.0, 0.0],
                negative_id: [-1.0, 0.0, 0.0, 0.0],
            }
        )
        self._insert_annotation_with_labels(
            1,
            [
                {"paragraph_id": positive_id, "emotion": 0},
                {"paragraph_id": negative_id, "emotion": 0},
            ],
        )
        await run_linguistic(self.run_id, self.db_session)
        rows = self._feature_rows()
        assert all(row.boundary_pos_score_sum is None for row in rows)
