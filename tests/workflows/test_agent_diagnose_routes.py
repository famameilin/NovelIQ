"""诊断 Agent 路由测试

本文件保留数据层取证测试，并通过 patch run_diagnosis_agent 验证工作流落库。

取证事实源：测试数据写入 paragraphs/paragraph_topics/paragraph_curves，
高张力素材来自 paragraph_features 的 tension_z 正式观测；伏笔树根按事件声明写入；
诊断落库断言按 diagnosis_reports/analysis_assessments 的正式读接口与 run 作用域查询。
"""

import json
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.diagnosis.queries import DiagnosisQueries
from src.diagnosis.read import fetch_diagnosis_payload
from src.diagnosis.schema import AgentAnalysis
from src.storage.repositories import ChapterRepository, ParagraphRepository, RunRepository
from src.storage.repositories.paragraph import insert_paragraph_tension_observations
from src.storage.repositories.paragraph_repository import ParagraphCurveRow
from src.text_processing.models import Chunk
from src.text_processing.paragraphs import split_chunk_paragraphs
from src.workflows.diagnose import run_diagnose
from tests.support.analysis_factories import insert_test_novel
from tests.support.chapter_annotation_helpers import character_fact, persist_chapter_annotation
from tests.support.model_stream_adapter import StreamedFakeModelMixin


class _EvidenceThenFinishLLM(StreamedFakeModelMixin):
    """按真实派发职责生成程序：每声明一个事件工作，比较与配对按真实归属尝试"""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def bind_tools(self, tools):
        assert [tool.name for tool in tools] == ["execute_code", "finish"]
        return self

    async def ainvoke(self, messages):
        for message in messages:
            if getattr(message, "type", None) == "tool" and getattr(message, "name", None) == "execute_code":
                assert json.loads(message.content)["status"] in {"applied", "partial"}, message.content
        assert not str(messages[-1].content).startswith("程序完整性检查未通过"), messages[-1].content
        material = next(
            json.loads(message.content)
            for message in reversed(messages)
            if isinstance(message.content, str) and message.content.startswith('{"role":')
        )
        self.calls += 1
        role = material["role"]
        if role == "case":
            # 案例会话自取未承诺案例：接手承诺后直接写入完成；无未承诺案例即结束
            code = (
                'cases = search_cases(unresolved_only=True)\n'
                'if cases:\n'
                '    case = cases[0]\n'
                '    promise_case(case_id=case["case_id"])\n'
                '    declaration = case["payload"]["event_id"]\n'
                '    page = search_events(limit=20)\n'
                '    source = read_event(node_id=declaration)["content"]\n'
                '    evidence = [{"paragraph_id":source["evidence"][0]["paragraph_id"]}]\n'
                '    own = write_event(items=[{"operation":"identity", "key":declaration, '
                '"title":source["title"], "problem":source["problem"], "summary":source["summary"], '
                '"event_type":source["event_type"], "status":source["status"], '
                '"declaration_ids":[declaration], "stage_order":[declaration], '
                '"current_declaration_id":declaration, "reason":"按真实章节核对身份", "evidence":evidence}], '
                'caseid=case["case_id"])["results"][0]["event_id"]\n'
                '    write_event(items=[{"operation":"declaration_review", "declaration_ids":[declaration], '
                '"reason":"逐项核对已保存章节声明"}], caseid=case["case_id"])\n'
                '    targets = []\n'
                '    for item in page["events"]:\n'
                '        if item["chapter_id"] > source["chapter_id"]:\n'
                '            targets = targets + [item["declaration_id"]]\n'
                '    if targets:\n'
                '        write_event(items=[{"operation":"compare", "source_declaration_id":declaration, '
                '"target_declaration_ids":targets, "disposition":"independent", '
                '"reason":"本测试各章问题明确独立", "evidence":evidence}], caseid=case["case_id"])\n'
                '    pairs = []\n'
                '    for item in search_events(kind="event", limit=20)["events"]:\n'
                '        if item["event_id"] != own:\n'
                '            pairs = pairs + [{"operation":"structure_review", "source_event_id":own, '
                '"target_event_id":item["event_id"], "disposition":"independent", '
                '"reason":"本测试各事件没有包含或因果关系", "evidence":evidence}]\n'
                '    if pairs:\n'
                '        write_event(items=pairs, caseid=case["case_id"])\n'
                'else:\n'
                '    finish()'
            )
        else:
            assert role == "report"
            code = f'read_metrics()\nread_topics()\nwrite_diagnosis(analysis={self.payload!r})\nfinish()'
        return AIMessage(
            content="",
            tool_calls=[{"name": "execute_code", "args": {"code": code}, "id": f"p{self.calls}", "type": "tool_call"}],
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
    def setup(self, db_session, configured_model_pool, monkeypatch):
        from src.config import settings

        monkeypatch.setattr(settings.models.model_pool[0], "max_tokens", 16000)
        # 案例会话数=池条目并发位；固定为 1 使自取顺序确定
        monkeypatch.setattr(settings.models.model_pool[0], "max_in_flight", 1)
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
        # 主题三表契约：模型契约 + 每段一行状态 + 完整分布
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
                    pos_density=None,
                    neg_density=None,
                    net_density=None,
                    smoothed_net_density=0.05,
                    surface_tension=None,
                    smoothed_surface_tension=0.5,
                )
                for span in spans
            ],
        )
        # 高张力素材来自 paragraph_features 的 tension_z 正式观测（z=0 → 投影 0.5）
        insert_paragraph_tension_observations(
            self.db_session, self.run_id, [(span.paragraph_id, 0.0) for span in spans]
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
                # 本 fixture 未发布完整事件：第 1 章声明标为伏笔树根，验证发布前章节伏笔
                # 投影按来源声明回退（事件身份保持空，不冒充正式事件）
                events=[
                    {
                        "description": f"第{i}章独立的测试问题",
                        **({"isforeshadowing": True, "payoff_likelihood": "high"} if i == 0 else {}),
                    }
                ],
            )

        self.db_session.commit()
        self._register_event_cases()

    def _register_event_cases(self) -> None:
        """声明落地即登记事件案例（生产由标注工具登记、章保存落库）：诊断期按案例自取办理"""
        from sqlalchemy import select

        from src.case_pool import CasePool
        from src.case_pool.contributions import CaseContribution
        from src.storage.models import ChapterAnnotation, EventDeclaration
        from tests.support.chapter_annotation_helpers import _create_work_identity

        _work_id, author = _create_work_identity(
            self.db_session, run_id=self.run_id, chapter_id=1, role="event"
        )
        pool = CasePool(self.run_id)
        pool.begin(author)
        rows = self.db_session.execute(
            select(
                EventDeclaration.declaration_id,
                EventDeclaration.title,
                EventDeclaration.summary,
                EventDeclaration.status,
                ChapterAnnotation.chapter_id,
            )
            .join(ChapterAnnotation, ChapterAnnotation.record_id == EventDeclaration.record_id)
            .where(ChapterAnnotation.run_id == self.run_id)
        ).all()
        for declaration_id, title, summary, status, chapter_id in rows:
            pool.register_event_case(
                declaration_id=declaration_id,
                title=title,
                summary=summary,
                status=status,
                chapter_id=int(chapter_id),
                author=author,
            )
        assert pool.save_work(
            self.db_session,
            CaseContribution(
                self.run_id,
                author,
                json.dumps(
                    {
                        "created_case_ids": sorted(pool.created.get(author, set())),
                        "registrations": {
                            key: pool.cases[key] for key in sorted(pool.registrations.get(author, set()))
                        },
                        "deliveries": [],
                    },
                    ensure_ascii=False,
                ),
            ),
        ) == []
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
        assert llm.calls == 7  # 五件事件案例逐件办理与一次收尾，加一份报告
        assert analysis.genre_labels == ["通用"]
        assert analysis.style_labels == ["严肃"]

        # 正式产物按 run 作用域读：报告头 + 标签条目
        fetched = fetch_diagnosis_payload(self.db_session, self.run_id)
        assert fetched is not None
        assert fetched["genre_labels"] == ["通用"]
        assert fetched["style_labels"] == ["严肃"]
        assert fetched["diagnosis"] == "ok"

    @pytest.mark.asyncio()
    async def test_case_session_save_survives_failure_and_resume_skips_done_cases(self) -> None:
        """会话做完保存一次：报告保存失败时已办案例与承诺随会话落库，续跑水合后不重办"""
        from src.case_pool import CasePool
        from src.event_trees.storage_map import run_events

        self._create_full_data(3)
        llm = _EvidenceThenFinishLLM(_fake_analysis(self.novel_id).model_dump())
        with patch("src.model_pool.llm.build_chat_model", return_value=llm):
            with patch(
                "src.agents.diagnosis.domain.save_diagnosis_result",
                side_effect=RuntimeError("模拟报告保存失败"),
            ):
                with pytest.raises(RuntimeError, match="模拟报告保存失败"):
                    await run_diagnose(run_id=self.run_id, session=self.db_session)

        saved_event_ids = set(run_events(self.db_session, self.run_id))
        assert saved_event_ids
        pool = CasePool(self.run_id)
        pool.load_storage(self.db_session)
        promised = [item for item in pool.search() if item["promised"]]
        assert len(promised) == len(saved_event_ids)

        with patch("src.model_pool.llm.build_chat_model", return_value=llm):
            analysis = await run_diagnose(run_id=self.run_id, session=self.db_session)
        assert analysis is not None
        # 续跑：案例会话对空池一次 finish、报告会话一次收尾，不重复办理既有案例
        assert llm.calls == 5 + 2
        assert set(run_events(self.db_session, self.run_id)) == saved_event_ids
        fetched = fetch_diagnosis_payload(self.db_session, self.run_id)
        assert fetched is not None and fetched["diagnosis"] == "ok"

    @pytest.mark.asyncio()
    async def test_run_diagnose_persists_result(self) -> None:
        self._create_full_data(3)

        llm = _EvidenceThenFinishLLM(_fake_analysis(self.novel_id).model_dump())
        with patch("src.model_pool.llm.build_chat_model", return_value=llm):
            await run_diagnose(
                run_id=self.run_id,
                session=self.db_session,
            )

        assert llm.calls == 5  # 三件事件案例逐件办理与一次收尾，加一份报告
        fetched = fetch_diagnosis_payload(self.db_session, self.run_id)
        assert fetched is not None
        assert fetched["novel_id"] == self.novel_id
        assert fetched["genre_labels"] == ["通用"]
        assert fetched["style_labels"] == ["严肃"]
        assert fetched["narrative_arc_type"] == "白手起家"
        assert fetched["focus_structure"] == "dual"
        assert "角色0" in fetched["focus_characters"]
        assert "角色0" in fetched["main_characters"]
        assert "角色1" in fetched["core_cast"]
