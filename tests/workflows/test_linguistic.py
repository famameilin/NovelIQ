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
            words = list(sentence)
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

        # 词表命中计入正式密度；四字候选行不计
        phrase_rows = LinguisticRepository(self.db_session).fetch_phrase_hits(self.run_id)
        lexicon_rows = [row for row in phrase_rows if row.match_kind == "lexicon"]
        assert lexicon_rows and all(row.is_metric_hit for row in lexicon_rows)
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
