"""语言结构阶段集成测试（run_linguistic）

LTP 推理用 FakeLtpSession 替换（真实 LTP 模型只做模块级验证），
analyze_paragraph 纯函数路径保持真实；短语匹配与 Word2Vec 全真实。

逐段事实落 linguistic_spans（词元/NER/短语三类互斥
区间）与 linguistic_arcs（dep:*/sdp:*），句式五类计数落 paragraph_features；
完成事实（linguistic_completed_at/phrase_completed_at）与共享句数落
paragraph_metrics；run 级 LTP/短语/w2v 合同落 analysis_runs。派生量（词长分组、
POS 分组、依存统计、词典对照、情绪事件）不落库，由读取投影从正式事实重算，
因此本文件按同一投影断言。固定短语只有一个运行级来源（fixed_phrases 词表），
不再扫描 draft 词表。
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text

from src.linguistic import ltp_client
from src.linguistic.queries import fetch_entity_candidates
from src.linguistic.storage_projection import project_linguistic_features
from src.storage import new_id
from tests.support.storage_fixtures import storage_for

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config.constants.contracts import FIXED_CONTRACT_VERSION, FIXED_PHRASE_METRIC_ENABLED
from src.lexicons.constants import LEXICON_FILES
from src.linguistic.ltp_client import LTP_PIPELINE_VERSION, LtpPipelineOutput, ltp_pipeline_contract
from src.storage.repositories import ChapterRepository, ParagraphRepository, RunRepository
from src.storage.repositories.linguistic_repository import LinguisticRepository
from src.text_processing.models import Chunk
from src.text_processing.paragraphs import split_chunk_paragraphs
from src.workflows.linguistic import run_linguistic
from tests.support.analysis_factories import insert_test_novel

_TEST_TEXTS = ["江湖快意恩仇，刀光剑影之间英雄辈出。", "他叫汤姆去拿外衣，但是天色已晚。"]

#: 旧并行事实表不得存在（本切片的回归护栏）
_RETRACTED_TABLES = (
    "paragraph_linguistic_completions",
    "paragraph_tokens",
    "paragraph_dependency_arcs",
    "paragraph_syntax_observations",
    "paragraph_emotion_observations",
    "paragraph_emotion_events",
    "paragraph_entities",
    "paragraph_phrase_hits",
    "phrase_lexicon_contracts",
    "paragraph_pos_embeddings",
    "paragraph_embeddings",
    "linguistic_runs",
    "ltp_pos_mappings",
    "ltp_entity_type_mappings",
    "embedding_model_runs",
)


def _create_run(db_session, novel_id: str) -> str:
    """创建最小分析运行行（novel 先行；运行创建语义允许不填来源快照）"""
    return RunRepository(db_session).create_run(novel_id=novel_id, source_path="test", title="Linguistic Test")


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
        return LtpPipelineOutput(cws=cws, pos=pos, ner=ner, dep=dep, sdp=[])


def _span_count(db_session, run_id: str, branch: str) -> int:
    """按语言区间分支统计行数（token/ner/phrase 三类互斥区间）"""
    branch_condition = {
        "token": "token_index IS NOT NULL",
        "ner": "raw_entity_type IS NOT NULL",
        "phrase": "phrase_match_kind IS NOT NULL",
    }[branch]
    return int(
        db_session.execute(
            text(f"SELECT COUNT(*) FROM linguistic_spans WHERE run_id = :run_id AND {branch_condition}"),
            {"run_id": run_id},
        ).scalar()
        or 0
    )


def _arc_count(db_session, run_id: str, prefix: str) -> int:
    return int(
        db_session.execute(
            text(
                "SELECT COUNT(*) FROM linguistic_arcs a "
                "JOIN linguistic_spans s ON s.span_id = a.dependent_span_id "
                "WHERE s.run_id = :run_id AND a.relation_code LIKE :prefix"
            ),
            {"run_id": run_id, "prefix": f"{prefix}%"},
        ).scalar()
        or 0
    )


def _metric_count(db_session, run_id: str, column: str) -> int:
    return int(
        db_session.execute(
            text(f"SELECT COUNT(*) FROM paragraph_metrics WHERE run_id = :run_id AND {column} IS NOT NULL"),
            {"run_id": run_id},
        ).scalar()
        or 0
    )


def _feature_count(db_session, run_id: str, code_prefix: str) -> int:
    return int(
        db_session.execute(
            text("SELECT COUNT(*) FROM paragraph_features WHERE run_id = :run_id AND feature_code LIKE :prefix"),
            {"run_id": run_id, "prefix": f"{code_prefix}%"},
        ).scalar()
        or 0
    )


def test_retracted_parallel_tables_are_absent(db_session) -> None:
    """语言/主题/向量的旧拆分表与旧宽表不得存在于运行库"""
    rows = db_session.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = ANY(:names)"
        ),
        {"names": list(_RETRACTED_TABLES)},
    ).scalars()
    assert list(rows) == []


class TestRunLinguistic:
    @pytest.fixture(autouse=True)
    def setup(self, db_session, monkeypatch):
        self.db_session = db_session
        self.novel_id = new_id()
        insert_test_novel(self.novel_id, session=db_session)
        self.run_id = _create_run(db_session, self.novel_id)

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

    def _feature_rows(self) -> Sequence[Any]:
        return project_linguistic_features(LinguisticRepository(self.db_session).fetch_linguistic_sources(self.run_id))

    @pytest.mark.asyncio()
    async def test_runs_all_steps_and_writes_linguistic_relations(self) -> None:
        paragraphs, features = await run_linguistic(self.run_id, storage_for(self.db_session))
        assert paragraphs == 2
        assert features == 2

        # 完成事实区分"未处理"与"零词元"：两段语言完成、两段短语完成
        assert _metric_count(self.db_session, self.run_id, "linguistic_completed_at") == 2
        assert _metric_count(self.db_session, self.run_id, "phrase_completed_at") == 2
        # 逐段事实：词元区间、依存弧、句式五类计数（每段一行）
        assert _span_count(self.db_session, self.run_id, "token") > 0
        assert _arc_count(self.db_session, self.run_id, "dep:") > 0
        assert _feature_count(self.db_session, self.run_id, "sentence_") == 10
        # NER 候选（汤姆 Nh → person）与固定短语命中（刀光剑影等）
        assert _span_count(self.db_session, self.run_id, "ner") > 0
        assert _span_count(self.db_session, self.run_id, "phrase") > 0

        # run 级合同：LTP 管线/模型 + 唯一固定短语词表来源与计量合同
        contract = self.db_session.execute(
            text(
                "SELECT ltp_pipeline_version, ltp_model_key, fixed_phrase_lexicon_key, "
                "fixed_phrase_contract_version FROM analysis_runs WHERE run_id = :run_id"
            ),
            {"run_id": self.run_id},
        ).one()
        assert contract.ltp_pipeline_version == LTP_PIPELINE_VERSION
        assert contract.ltp_model_key == ltp_pipeline_contract()[1]
        assert contract.fixed_phrase_lexicon_key == LEXICON_FILES["fixed_phrases"]
        assert contract.fixed_phrase_contract_version == FIXED_CONTRACT_VERSION

        repo = LinguisticRepository(self.db_session)
        entity_rows = repo.fetch_entities(self.run_id)
        assert entity_rows and entity_rows[0].surface_text == "汤姆"
        assert (
            fetch_entity_candidates(self.run_id, storage_for(self.db_session))["entities"][0]["normalized_entity_type"]
            == "person"
        )

        # 契约关闭正式短语计量：lexicon 命中与四字候选都不计入正式密度
        phrase_rows = repo.fetch_phrase_hits(self.run_id)
        assert phrase_rows
        assert FIXED_PHRASE_METRIC_ENABLED is False
        assert all(not row.is_metric_hit for row in phrase_rows)
        lexicon_rows = [row for row in phrase_rows if row.match_kind == "lexicon"]
        assert lexicon_rows and all(not row.is_metric_hit for row in lexicon_rows)
        # 词面按原文切片投影，命中区间与原文自洽
        assert all(row.surface_text for row in lexicon_rows)
        assert all(row.local_end_char - row.local_start_char == len(row.surface_text) for row in lexicon_rows)

        rows = self._feature_rows()
        assert len(rows) == 2
        assert all(row.paragraph_id in (0, 1) for row in rows)
        # 词元总数 / 词长分组 / POS 分组由事实行投影，且与事实行守恒
        assert sum(row.ltp_token_count for row in rows) == _span_count(self.db_session, self.run_id, "token")
        for row in rows:
            assert sum(row.word_length_counts.values()) == row.ltp_token_count
            assert sum(row.pos_counts.values()) == row.ltp_token_count

    @pytest.mark.asyncio()
    async def test_cancel_takes_effect_at_paragraph_batch_boundary(self) -> None:
        """取消在段落批边界生效：不会把整卷 LTP 跑完才响应，也不写完整结果"""
        checks = {"count": 0}

        def is_cancelled() -> bool:
            checks["count"] += 1
            return checks["count"] > 1

        with pytest.raises(asyncio.CancelledError):
            await run_linguistic(self.run_id, storage_for(self.db_session), batch_size=1, is_cancelled=is_cancelled)

        # 第一批已放行、第二批边界命中取消：没跑完整卷
        assert checks["count"] >= 2
        assert _metric_count(self.db_session, self.run_id, "linguistic_completed_at") < 2

    @pytest.mark.asyncio()
    async def test_ltp_inference_runs_off_event_loop(self, monkeypatch) -> None:
        """LTP 批推理必须运行在工作线程

        LTP 批推理是重 CPU 同步调用，直接在事件循环上跑会冻结整个 API；
        to_thread 后调用线程必须是工作线程而非事件循环主线程。
        """
        import threading

        import src.linguistic as linguistic_module
        from src.linguistic import analyze_paragraph_batch as original_impl

        observed_threads: list[int] = []

        def _spy(texts):
            observed_threads.append(threading.get_ident())
            return original_impl(texts)

        monkeypatch.setattr(linguistic_module, "analyze_paragraph_batch", _spy)

        event_loop_thread = threading.get_ident()
        paragraphs, features = await run_linguistic(self.run_id, storage_for(self.db_session))

        assert paragraphs == 2
        assert observed_threads, "LTP 批推理未被执行"
        assert all(t != event_loop_thread for t in observed_threads), "LTP 推理仍阻塞事件循环"

    @pytest.mark.asyncio()
    async def test_word2vec_enabled_trains_and_writes_contract(self, monkeypatch, tmp_path) -> None:
        """验证共享 kv 初始化后写入实际来源与 run 私有模型契约"""

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
            """把工作流 run 模型路径隔离到临时目录"""
            assert candidate_run_id == self.run_id
            assert kind == "word2vec"
            return run_model_dir

        monkeypatch.setattr(
            "src.config.paths.resolve_run_model_dir",
            resolve_test_run_model_dir,
        )

        try:
            paragraphs, features = await run_linguistic(self.run_id, storage_for(self.db_session))
        finally:
            reset_pretrained_cache()
        assert paragraphs == 2
        assert features == 2

        model_run = LinguisticRepository(self.db_session).fetch_word2vec_model_run(self.run_id)
        assert model_run is not None
        assert model_run.embedding_dimension == 4
        # 训练参数按 analysis_runs.w2v_* 明确列落库
        assert model_run.window_size == _settings.linguistic.word2vec.window
        assert model_run.min_count == 1
        assert model_run.epochs == 1
        assert model_run.pretrained_vocabulary_size == 4
        assert Path(model_run.source_uri) == kv_path.resolve()
        assert (run_model_dir / "word2vec.model").is_file()
        assert _feature_count(self.db_session, self.run_id, "pos_vector:") > 0

        # source_token_count 由正式词元 × 版本 POS 分组投影（分母不落库不漂移）
        feature_rows = self._feature_rows()
        expected_noun_total = sum(row.pos_counts.get("noun", 0) for row in feature_rows)
        coverage = LinguisticRepository(self.db_session).fetch_pos_embedding_coverage(
            self.run_id, ltp_client.POS_GROUP_MAP
        )
        coverage_by_group = {row.pos_group: int(row.source_total) for row in coverage}
        assert coverage_by_group.get("noun", 0) == expected_noun_total

    @pytest.mark.asyncio()
    async def test_rerun_clears_and_reinserts(self) -> None:
        await run_linguistic(self.run_id, storage_for(self.db_session))

        def _tracked() -> dict[str, int]:
            return {
                "token_spans": _span_count(self.db_session, self.run_id, "token"),
                "ner_spans": _span_count(self.db_session, self.run_id, "ner"),
                "phrase_spans": _span_count(self.db_session, self.run_id, "phrase"),
                "arcs": _arc_count(self.db_session, self.run_id, "dep:"),
                "sentence_features": _feature_count(self.db_session, self.run_id, "sentence_"),
                "linguistic_completed": _metric_count(self.db_session, self.run_id, "linguistic_completed_at"),
                "phrase_completed": _metric_count(self.db_session, self.run_id, "phrase_completed_at"),
            }

        first = _tracked()
        assert first["token_spans"] > 0 and first["linguistic_completed"] == 2

        await run_linguistic(self.run_id, storage_for(self.db_session))
        assert _tracked() == first

    @pytest.mark.asyncio()
    async def test_ltp_disabled_skips_all_linguistic_steps(self, monkeypatch) -> None:
        """LTP 关闭 → 无完成事实与语言事实行；短语匹配依赖语言完成（同闸门），一并跳过"""
        from src.config import settings as _settings

        monkeypatch.setattr(_settings.linguistic.ltp, "enabled", False)
        paragraphs, features = await run_linguistic(self.run_id, storage_for(self.db_session))
        assert paragraphs == 2
        assert features == 0
        assert _metric_count(self.db_session, self.run_id, "linguistic_completed_at") == 0
        assert _metric_count(self.db_session, self.run_id, "phrase_completed_at") == 0
        assert _span_count(self.db_session, self.run_id, "token") == 0
        assert _span_count(self.db_session, self.run_id, "phrase") == 0
        fixed_key = self.db_session.execute(
            text("SELECT fixed_phrase_lexicon_key FROM analysis_runs WHERE run_id = :run_id"),
            {"run_id": self.run_id},
        ).scalar_one()
        assert fixed_key is None

    @pytest.mark.asyncio()
    async def test_batch_size_one_produces_same_rows_as_full_batch(self) -> None:
        """分批落库与一次全量落库结果一致（clear_first 只在首批生效，后续批追加）"""
        await run_linguistic(self.run_id, storage_for(self.db_session), batch_size=1)
        batched = {
            "token_spans": _span_count(self.db_session, self.run_id, "token"),
            "ner_spans": _span_count(self.db_session, self.run_id, "ner"),
            "phrase_spans": _span_count(self.db_session, self.run_id, "phrase"),
            "linguistic_completed": _metric_count(self.db_session, self.run_id, "linguistic_completed_at"),
        }
        assert batched["linguistic_completed"] == 2

        # 清空后按默认大 batch 重跑，验证完全一致
        await run_linguistic(self.run_id, storage_for(self.db_session))
        assert {
            "token_spans": _span_count(self.db_session, self.run_id, "token"),
            "ner_spans": _span_count(self.db_session, self.run_id, "ner"),
            "phrase_spans": _span_count(self.db_session, self.run_id, "phrase"),
            "linguistic_completed": _metric_count(self.db_session, self.run_id, "linguistic_completed_at"),
        } == batched

    @pytest.mark.asyncio()
    async def test_empty_run_returns_zero(self) -> None:
        novel_id = new_id()
        insert_test_novel(novel_id, session=self.db_session)
        empty_run = _create_run(self.db_session, novel_id)
        paragraphs, features = await run_linguistic(empty_run, storage_for(self.db_session))
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
    """mNEG 接管词典否定翻转——paragraph_metrics 回写 + 曲线重算"""

    @pytest.fixture(autouse=True)
    def setup(self, db_session, monkeypatch):
        self.db_session = db_session
        self.novel_id = new_id()
        insert_test_novel(self.novel_id, session=db_session)
        self.run_id = _create_run(db_session, self.novel_id)

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
                )
            ],
        )

    @pytest.mark.asyncio()
    async def test_mneg_flip_rewrites_metrics_and_stores_comparison(self) -> None:
        paragraphs, features = await run_linguistic(self.run_id, storage_for(self.db_session))
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

        feature = project_linguistic_features(
            LinguisticRepository(self.db_session).fetch_linguistic_sources(self.run_id)
        )[0]
        assert float(feature.lexicon_pos_count) == 1.0
        assert float(feature.mneg_neg_count) == 1.0
        assert feature.emotion_event_count == 1
        event = feature.emotion_events[0]
        # 谓词词面按原文切片投影（弧行只存词元区间与关系码）
        assert event["predicate"] == "高兴"
        assert event["predicate_token_index"] == 3
        assert event["negated"] is True
        assert event["holder"] is None
        assert event["degree_words"] == []
        # 语义依存弧留库（sdp:mNEG 一条），词典/边界观测不进语言事实行
        assert _arc_count(self.db_session, self.run_id, "sdp:") == 1
        sdp_code = self.db_session.execute(
            text(
                "SELECT a.relation_code FROM linguistic_arcs a "
                "JOIN linguistic_spans s ON s.span_id = a.dependent_span_id "
                "WHERE s.run_id = :run_id AND a.relation_code LIKE 'sdp:%'"
            ),
            {"run_id": self.run_id},
        ).scalar_one()
        assert sdp_code == "sdp:mNEG"

        # 曲线按修正分子重算（净密度由指标分子/分母投影）：net_density = (0 - 1) / 4
        curve_row = ParagraphRepository(self.db_session).fetch_paragraph_curves(self.run_id)[0]
        assert int(curve_row.paragraph_id) == 0
        assert float(curve_row.net_density) == -0.25


class TestParagraphBoundary:
    """段落级监督（按书边界）：自选段标签→段落向量边界→逐段打分回写

    标签读 analysis_assessments 的逐段情绪形状（经章节标注产物头
    关联本 run 的标注 work），段落向量读 paragraph_features 的 semantic_vector 行，
    打分回写 paragraph_metrics 的 boundary_*_score_sum 列。
    """

    @pytest.fixture(autouse=True)
    def setup(self, db_session, monkeypatch):
        self.db_session = db_session
        self.novel_id = new_id()
        insert_test_novel(self.novel_id, session=db_session)
        self.run_id = _create_run(db_session, self.novel_id)

        chapters = [
            Chunk(index=i, start=i * 100, end=i * 100 + len(text), text=text, chapter_id=i + 1)
            for i, text in enumerate(_TEST_TEXTS)
        ]
        ChapterRepository(db_session).insert_chapter_texts(self.run_id, chapters)
        spans = [replace(span, token_count=2) for span in split_chunk_paragraphs(chapters)]
        paragraph_repo = ParagraphRepository(db_session)
        paragraph_repo.insert_paragraphs(self.run_id, spans)

        # 边界观测列在 paragraph_metrics 上：先落指标行（真实链由 preprocess 落）
        from src.storage.repositories.paragraph_repository import ParagraphMetricRow

        paragraph_repo.insert_paragraph_metrics(
            self.run_id,
            [
                ParagraphMetricRow(
                    paragraph_id=span.paragraph_id,
                    token_count=2,
                    sentence_count=1,
                    sentence_char_sum=2.0,
                    sentence_char_sum_sq=4.0,
                    positive_weight_sum=0.0,
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
                )
                for span in spans
            ],
        )

        from src.config import settings as _settings
        from src.linguistic import ltp_client

        monkeypatch.setattr(ltp_client.LtpSession, "get_instance", lambda: FakeLtpSession())
        monkeypatch.setattr(_settings.linguistic.word2vec, "enabled", False)
        yield

    def _feature_rows(self) -> Sequence[Any]:
        return project_linguistic_features(LinguisticRepository(self.db_session).fetch_linguistic_sources(self.run_id))

    def _insert_labels(self, labels: list[tuple[int, int]]) -> None:
        """直接落正式条目行：executions → chapter_annotations → analysis_assessments

        真实执行（标注角色 + 章 + run）直接携带归属；正式产物头同样落 run/章/角色。
        """
        from collections import defaultdict

        from src.storage.models import (
            AnalysisAssessment,
            ChapterAnnotation,
            Execution,
            Paragraph,
        )

        chapter_of = {
            int(row.paragraph_id): int(row.chapter_id)
            for row in self.db_session.execute(
                select(Paragraph.paragraph_id, Paragraph.chapter_id).where(Paragraph.run_id == self.run_id)
            ).all()
        }
        by_chapter: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for paragraph_id, emotion in labels:
            by_chapter[chapter_of[paragraph_id]].append((paragraph_id, emotion))

        now = datetime.now(UTC).replace(tzinfo=None)
        for chapter_id, chapter_labels in by_chapter.items():
            execution_id = new_id()
            record_id = new_id()
            self.db_session.add(
                Execution(
                    execution_id=execution_id,
                    run_id=self.run_id,
                    role="annotation",
                    chapter_id=chapter_id,
                    attempt_number=1,
                    started_at=now,
                    status="success",
                )
            )
            self.db_session.flush()  # 明确顺序：execution → annotation 头 → 逐段条目
            self.db_session.add(
                ChapterAnnotation(
                    record_id=record_id,
                    execution_id=execution_id,
                    run_id=self.run_id,
                    chapter_id=chapter_id,
                    role="annotation",
                    contract_version="test-contract",
                    chapter_consolidation_version="test-consolidation",
                    summary="测试",
                    emotional_valence=0,
                    narrative_function="setup",
                    pivot_moment=False,
                    cliffhanger=False,
                    created_at=now,
                    saved_at=now,
                )
            )
            self.db_session.flush()
            for paragraph_id, emotion in chapter_labels:
                self.db_session.add(
                    AnalysisAssessment(
                        assessment_id=new_id(),
                        record_id=record_id,
                        paragraph_id=paragraph_id,
                        emotion=str(emotion),
                    )
                )
        self.db_session.commit()

    def _insert_paragraph_embeddings(self, vectors_by_id: dict[int, list[float]]) -> None:
        """经正式入口写 paragraph_features 的 semantic_vector 行 + 运行模型合同"""
        from src.storage.repositories.paragraph.embedding_ops import (
            ParagraphEmbeddingRow,
            insert_paragraph_embeddings,
        )

        dimension = len(next(iter(vectors_by_id.values())))
        insert_paragraph_embeddings(
            self.db_session,
            self.run_id,
            [ParagraphEmbeddingRow(paragraph_id=pid, embedding_vector=vector) for pid, vector in vectors_by_id.items()],
            embedding_dimension=dimension,
        )
        self.db_session.commit()

    @pytest.mark.asyncio()
    async def test_no_labels_keeps_boundary_columns_null(self) -> None:
        """无标签 run：两列 NULL，段落曲线维持 mNEG 口径"""
        await run_linguistic(self.run_id, storage_for(self.db_session))
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
        self._insert_labels([(positive_id, 2), (negative_id, -2)])

        await run_linguistic(self.run_id, storage_for(self.db_session))

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
        self._insert_labels(
            [
                (positive_id, 2),
                # 第二标签指向无向量的段落：fit 只用能对上向量的样本
                (negative_id, -2),
            ]
        )

        await run_linguistic(self.run_id, storage_for(self.db_session))
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
        self._insert_labels([(positive_id, 0), (negative_id, 0)])

        await run_linguistic(self.run_id, storage_for(self.db_session))
        rows = self._feature_rows()
        assert all(row.boundary_pos_score_sum is None for row in rows)
