"""真实队列、审计和保存验证两种结束信号及预算终局"""

from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import func, select

from src.audit.queries import fetch_agent_turns
from src.config import settings
from src.storage.models import Agent, ChapterAnnotation
from src.work.chapter_pool import PipelineWorkFailed
from src.work.queries import chapter_annotations, fetch_annotation_role_records
from src.workflows.annotate import run_annotate
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.storage_fixtures import storage_for
from tests.workflows.test_annotation_work_pipeline import ProgramModel


@pytest.mark.parametrize("signal", ["no_tool", "finish"])
async def test_missing_completion_keeps_history_variables_and_invocation(db_session, monkeypatch, signal):
    monkeypatch.setattr(settings.models.annotation, "max_iterations", 3)
    novel, run = create_run_with_chunks(db_session, texts=["原文行动。"])

    class Model(ProgramModel):
        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                code = 'summary = "原文行动"'
            elif self.calls == 2:
                if signal == "no_tool":
                    return AIMessage(content="完成")
                code = "finish()"
            else:
                assert "metrics" in str(messages)
                code = 'finish()\nmetric(summary=summary, emotional_valence=0, narrative_function="铺垫")'
            return AIMessage(
                content="", tool_calls=[{"name": "execute_code", "args": {"code": code}, "id": str(self.calls)}]
            )

    model = Model("")
    with patch("src.model_pool.llm.build_chat_model", return_value=model) as factory:
        assert await run_annotate(run, storage_for(db_session), novel_id=novel) == (1, 0, 1)
    assert model.calls == 3 and factory.call_count == 1
    db_session.expire_all()
    turns = fetch_agent_turns(storage_for(db_session), run)
    assert len(turns) == 3 and len({turn.agent_id for turn in turns}) == 1
    output = chapter_annotations(storage_for(db_session), run)[0]
    assert output.payload["metrics"]["summary"] == "原文行动"


async def test_no_tool_after_complete_write_saves_without_finish(db_session):
    novel, run = create_run_with_chunks(db_session, texts=["原文行动。"])

    class Model(ProgramModel):
        async def ainvoke(self, messages):
            if self.calls == 1:
                self.calls += 1
                return AIMessage(content="完成")
            return await super().ainvoke(messages)

    model = Model('metric(summary="行动", emotional_valence=0, narrative_function="铺垫")')
    with patch("src.model_pool.llm.build_chat_model", return_value=model):
        assert await run_annotate(run, storage_for(db_session), novel_id=novel) == (1, 0, 1)
    assert model.calls == 2


async def test_budget_exhaustion_is_not_retried_and_keeps_audit(db_session, monkeypatch):
    monkeypatch.setattr(settings.models.annotation, "max_iterations", 1)
    novel, run = create_run_with_chunks(db_session, texts=["原文行动。", "尚未开始。"], chapter_ids=[1, 2])
    model = ProgramModel('metric(summary="行动", emotional_valence=0, narrative_function="铺垫")')
    with patch("src.model_pool.llm.build_chat_model", return_value=model) as factory:
        with pytest.raises(PipelineWorkFailed, match="budget_exhausted.*iterations_used=1.*iterations_limit=1"):
            await run_annotate(run, storage_for(db_session), novel_id=novel)
    # 即使其他 work 已在飞，各自最多调用一次；预算失败没有重新选模型
    db_session.expire_all()
    turns = fetch_agent_turns(storage_for(db_session), run)
    assert turns and factory.call_count == model.calls == len(turns)
    assert len({turn.agent_id for turn in turns}) == len(turns)
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ChapterAnnotation)
            .join(Agent, Agent.id == ChapterAnnotation.agent_id)
            .where(Agent.run_id == run)
        )
        == 0
    )
    # 预算终局没有任何正式产物：未保存角色由缺行表达
    assert fetch_annotation_role_records(storage_for(db_session), run) == []
