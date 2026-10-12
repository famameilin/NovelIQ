"""
诊断 Agent 路由测试

说明: 诊断已 agent 化（工具化自主取证），payload 构建与 DiagnosisClient 已移除；
     本文件保留数据层取证测试，并通过 patch run_diagnosis_agent 验证工作流落库

2026-08-14 M8a：取证事实源段落化——测试数据改为写入 paragraphs/paragraph_topics/
paragraph_curves（chunk_topics 已删除），高张力素材来自段落曲线 surface_tension。
"""

import sys
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.diagnosis.queries import DiagnosisQueries
from src.diagnosis.schema import AgentAnalysis
from src.storage.repositories import ChapterRepository, ParagraphRepository, RunRepository, StatsRepository
from src.storage.repositories.paragraph_repository import ParagraphCurveRow
from src.text_processing.models import Chunk
from src.text_processing.paragraphs import split_chunk_paragraphs
from src.workflows.diagnose import run_diagnose
from tests.support.analysis_factories import insert_test_novel
from tests.support.chapter_annotation_helpers import character_fact, persist_chapter_annotation
from tests.support.model_stream_adapter import StreamedFakeModelMixin


class _EvidenceThenFinishLLM(StreamedFakeModelMixin):
    """先调用取证工具再提交 finish 的假诊断模型，覆盖真实落库路径"""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def bind_tools(self, tools):
        del tools
        return self

    async def ainvoke(self, messages):
        del messages
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[{"name": "get_aggregate_signals", "args": {}, "id": "e1", "type": "tool_call"}],
            )
        return AIMessage(
            content="提交",
            tool_calls=[{"name": "finish", "args": {"analysis": self.payload}, "id": "f1", "type": "tool_call"}],
        )


def _fake_analysis(novel_id: str) -> AgentAnalysis:
    return AgentAnalysis(
        novel_id=novel_id,
        foreshadow_expectation=0.1,
        arc_scores={"角色0": 8.5, "角色1": 7.0},
        genre_labels=["通用"],
        style_labels=["严肃"],
        topic_labels={"0": "成长"},
        diagnosis="ok",
        narrative_arc_type="白手起家",
        focus_structure="dual",
        focus_characters=["角色0", "角色1"],
        main_characters=["角色0", "角色1"],
        core_cast=["角色0", "角色1"],
    )


class TestDiagnosisRoutes:
    @pytest.fixture(autouse=True)
    def setup(self, db_session):
        self.db_session = db_session
        self.novel_id = uuid.uuid4().hex[:8]
        insert_test_novel(self.novel_id, session=db_session)

        run_repo = RunRepository(db_session)
        self.run_id = run_repo.create_run(novel_id=self.novel_id, source_path="test", title="Test Novel")

    def _create_full_data(self, chunk_count: int = 5) -> None:
        chapter_repo = ChapterRepository(self.db_session)
        # M9a-2：每章一个运行时 chunk（chunk_id == chapter_id），
        # 段落坐标校验要求 global 坐标严格单调不重叠：偏移随章节序号递增
        chunks = [
            Chunk(
                index=i,
                start=i * 100,
                end=(i + 1) * 100,
                text=f"这是第{i}个测试文本，包含一些内容。",
                chapter_id=i + 1,
            )
            for i in range(chunk_count)
        ]
        chapter_repo.insert_chapter_texts(self.run_id, chunks)

        paragraph_repo = ParagraphRepository(self.db_session)
        spans = [replace(span, token_count=1) for span in split_chunk_paragraphs(chunks)]
        paragraph_repo.insert_paragraphs(self.run_id, spans)
        # 主题三表契约（§5.8-5.10）：模型契约 + 每段一行状态 + 完整分布
        paragraph_repo.insert_topic_model_run(
            self.run_id,
            model_key="gensim-lda",
            library_version="4.4.0",
            pipeline_version="1.0",
            num_topics=1,
            parameters={"num_topics": 1},
            dictionary_size=5,
            training_document_count=len(spans),
            inference_paragraph_count=len(spans),
            artifact_key=f"models/topic/{self.run_id}",
        )
        paragraph_repo.insert_paragraph_topic_inferences(
            self.run_id,
            [
                (
                    span.paragraph_id,
                    1,
                    1,
                    "complete",
                    None,
                    1.0,
                )
                for span in spans
            ],
        )
        paragraph_repo.insert_paragraph_topics(self.run_id, [(span.paragraph_id, 0, 1.0) for span in spans])
        paragraph_repo.insert_paragraph_curves(
            self.run_id,
            [
                ParagraphCurveRow(
                    paragraph_id=span.paragraph_id,
                    pos_density=0.1,
                    neg_density=0.05,
                    net_density=0.05 + span.paragraph_id * 0.01,
                    smoothed_net_density=0.05,
                    surface_tension=0.5,
                    smoothed_surface_tension=0.5,
                )
                for span in spans
            ],
        )

        for i in range(chunk_count):
            persist_chapter_annotation(
                self.db_session,
                run_id=self.run_id,
                chapter_id=i + 1,
                emotional_valences={i + 1: 1 if i % 2 == 0 else -1},
                event_types={i + 1: "冲突" if i in {1, 2} else "转折" if i == 3 else "铺垫"},
                pivot_chapters={i + 1} if i in {1, 2} else None,
                cliffhanger_chapters={chunk_count} if i == chunk_count - 1 else None,
                characters=[
                    character_fact(
                        chapter_id=i + 1,
                        name=f"角色{i}",
                        action="测试行为",
                        role_function="主体" if i == 0 else "客体",
                    )
                ],
            )
        # 2026-09-13 伏笔即事件树：向章 1 的事件标记伏笔树根
        from src.storage.models import EventNode

        root = self.db_session.query(EventNode).filter(EventNode.run_id == self.run_id).first()
        if root is not None:
            root.is_foreshadowing_root = True
            root.foreshadowing_status = "open"
            root.expected_payoff_family = "身份揭露"
            root.payoff_likelihood = "medium"

        self.db_session.commit()

    def test_fetch_pivot_blocks(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisQueries(self.db_session)
        blocks = diag_repo.fetch_pivot_blocks(self.run_id)
        assert len(blocks) > 0
        for block in blocks:
            assert len(block) == 3

    def test_fetch_high_tension_chunks(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisQueries(self.db_session)
        chunks = diag_repo.fetch_high_tension_chunks(self.run_id, limit=3)
        assert len(chunks) > 0
        for chunk in chunks:
            assert len(chunk) == 3

    def test_fetch_pivot_moments(self) -> None:
        self._create_full_data(5)

        diag_repo = DiagnosisQueries(self.db_session)
        moments = diag_repo.fetch_pivot_moments(self.run_id)
        assert len(moments) > 0

    @pytest.mark.asyncio()
    async def test_run_diagnose_agent_writes_db(self) -> None:
        """真 agent（假模型、真工具）跑完诊断后由 agent 自存产物"""
        self._create_full_data(5)

        llm = _EvidenceThenFinishLLM(_fake_analysis(self.novel_id).model_dump())
        with patch("src.model_pool.llm.build_chat_model", return_value=llm):
            analysis = await run_diagnose(
                run_id=self.run_id,
                session=self.db_session,
            )
        assert analysis is not None
        assert analysis.genre_labels == ["通用"]
        assert analysis.style_labels == ["严肃"]

        from sqlalchemy import select

        from src.storage.models import AnalysisOutput

        rows = list(
            self.db_session.execute(
                select(AnalysisOutput).where(
                    AnalysisOutput.run_id == self.run_id, AnalysisOutput.kind == "agent_analysis"
                )
            ).scalars()
        )
        assert len(rows) == 1
        assert rows[0].payload["genre_labels"] == ["通用"]

    @pytest.mark.asyncio()
    async def test_run_diagnose_persists_result(self) -> None:
        self._create_full_data(3)

        llm = _EvidenceThenFinishLLM(_fake_analysis(self.novel_id).model_dump())
        with patch("src.model_pool.llm.build_chat_model", return_value=llm):
            await run_diagnose(
                run_id=self.run_id,
                session=self.db_session,
            )

        stats_repo = StatsRepository(self.db_session)
        fetched = stats_repo.fetch_agent_analysis(self.run_id)
        assert fetched is not None
        assert fetched["novel_id"] == self.novel_id
        assert fetched["genre_labels"] == ["通用"]
        assert fetched["style_labels"] == ["严肃"]
        assert fetched["narrative_arc_type"] == "白手起家"
        assert fetched["focus_structure"] == "dual"
        assert "角色0" in fetched["focus_characters"]
        assert "角色0" in fetched["main_characters"]
        assert "角色1" in fetched["core_cast"]
        assert fetched["focus_structure"] == "dual"
        assert fetched["focus_characters"] is not None
        assert fetched["main_characters"] is not None
        assert fetched["core_cast"] is not None
        assert set(fetched) == {
            "novel_id",
            "narrative_organization",
            "foreshadow_expectation",
            "arc_scores",
            "genre_labels",
            "style_labels",
            "topic_labels",
            "diagnosis",
            "value_logic_type",
            "value_logic_reason",
            "power_stance_score",
            "power_stance_reason",
            "common_people_dignity",
            "dignity_reason",
            "cultural_depth_score",
            "cultural_depth_reason",
            "narrative_arc_type",
            "focus_structure",
            "focus_characters",
            "main_characters",
            "core_cast",
            "theme_color",
            "run_id",
        }
