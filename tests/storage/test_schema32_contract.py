"新运行、Agent 审计与案例的数据库约束"

import json
from datetime import datetime

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from src.storage.ids import new_id, new_task_id
from src.storage.models import Agent, AgentLoop, Base, Case, GlobalStats, Novel, Run, ToolCall
from src.storage.records.cases import CaseSave
from src.storage.repositories.audit_repository import AuditRepository
from src.storage.repositories.case_writes import CaseWritesRepository
from src.storage.repositories.stats.metrics import fetch_global_stats_dict, insert_global_stats


@pytest.fixture
def identities(db_session):
    novel = Novel(
        novel_id=new_id(), filename="schema32.txt", file_path="schema32.txt", file_size=10, upload_time=datetime.now()
    )
    db_session.add(novel)
    db_session.flush()
    runs = [Run(id=new_id(), novelid=novel.novel_id, taskid=new_task_id(), status="pending") for _ in range(2)]
    db_session.add_all(runs)
    db_session.flush()
    agents = [Agent(id=new_id(), run_id=run.id, type="case", status="running") for run in runs]
    agents.append(Agent(id=new_id(), run_id=runs[0].id, type="case", status="running"))
    db_session.add_all(agents)
    db_session.flush()
    return runs, agents


def contribution(run, author, case_id, *, promise=False):
    return CaseSave(
        run.id,
        author,
        json.dumps(
            {
                "registrations": {case_id: {"case_type": "event", "description": "核对原文冲突"}},
                "promises": [case_id] if promise else [],
            }
        ),
    )


def test_exact_physical_schema(db_session):
    assert len(Base.metadata.tables) == 32
    assert set(Run.__table__.c.keys()) == {"id", "novelid", "taskid", "status", "lda_completed", "w2v_completed"}
    assert set(Agent.__table__.c.keys()) == {"id", "run_id", "type", "status"}
    assert set(Case.__table__.c.keys()) == {
        "id",
        "run_id",
        "type",
        "description",
        "status",
        "producer_agent_id",
        "promised_agent_id",
    }
    assert "status" not in AgentLoop.__table__.c and "status" not in ToolCall.__table__.c
    schema = db_session.get_bind().get_execution_options()["schema_translate_map"][None]
    assert set(inspect(db_session.get_bind()).get_table_names(schema=schema)) == set(Base.metadata.tables)


def test_program_case_and_atomic_promise(db_session, identities):
    runs, agents = identities
    run = runs[0]
    case_id = new_id()
    repo = CaseWritesRepository(run.id)
    repo.save_work(db_session, contribution(run, None, case_id))
    case = db_session.get(Case, case_id)
    assert case.producer_agent_id is None and case.status == "pending"
    repo.save_work(db_session, contribution(run, agents[0].id, case_id, promise=True))
    db_session.refresh(case)
    assert case.status == "resolved" and case.promised_agent_id == agents[0].id
    with db_session.begin_nested():
        with pytest.raises(ValueError, match="其他 Agent"):
            repo.save_work(db_session, contribution(run, agents[2].id, case_id, promise=True))
    db_session.refresh(case)
    assert case.promised_agent_id == agents[0].id


def test_case_rollback_keeps_pending(db_session, identities):
    runs, agents = identities
    run = runs[0]
    case_id = new_id()
    repo = CaseWritesRepository(run.id)
    repo.save_work(db_session, contribution(run, None, case_id))
    with pytest.raises(RuntimeError):
        with db_session.begin_nested():
            repo.save_work(db_session, contribution(run, agents[0].id, case_id, promise=True))
            raise RuntimeError("产出保存失败")
    db_session.expire_all()
    assert db_session.get(Case, case_id).status == "pending"


def test_case_cross_run_trigger(db_session, identities):
    runs, agents = identities
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            Case(
                id=new_id(),
                run_id=runs[0].id,
                type="event",
                description="冲突",
                status="pending",
                producer_agent_id=agents[1].id,
            )
        )
        db_session.flush()


def test_global_stats_and_completed_defaults(db_session, identities):
    runs, _ = identities
    run = runs[0]
    assert run.lda_completed is False and run.w2v_completed is False
    insert_global_stats(db_session, run.id, [("emotion_avg", 0.4), ("rhythm_max", 2.0)])
    assert fetch_global_stats_dict(db_session, run.id) == {"emotion_avg": 0.4, "rhythm_max": 2.0}
    assert db_session.get(GlobalStats, run.id) is not None


def test_audit_one_row_per_observation(db_session, identities):
    runs, agents = identities
    repo = AuditRepository(db_session)
    turn = repo.start_turn(
        run_id=runs[0].id,
        agent_id=agents[0].id,
        role="case",
        turn_index=1,
        model="test",
        context_summary={},
        request_messages=[],
    )
    repo.finish_turn(turn, raw_response={}, error=None, timing={}, timing_notes=[], token_usage=None)
    repo.record_tool_call(turn_id=turn, call_index=1, tool_name="push_case", request_args={}, response={}, error=None)
    assert len(list(db_session.scalars(select(AgentLoop).where(AgentLoop.agent_id == agents[0].id)))) == 1
    assert len(list(db_session.scalars(select(ToolCall).where(ToolCall.agentloop_id == turn)))) == 1


def test_concurrent_promises_preserve_first_committed_owner(db_session, identities):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.orm import sessionmaker

    runs, agents = identities
    run, case_id = runs[0], new_id()
    repository = CaseWritesRepository(run.id)
    repository.save_work(db_session, contribution(run, None, case_id))
    run_id, owners = run.id, (agents[0].id, agents[2].id)
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind())
    barrier = Barrier(2)

    def promise(owner):
        request = CaseSave(run_id, owner, json.dumps({"registrations": {}, "promises": [case_id]}))
        with factory() as session:
            barrier.wait(timeout=5)
            try:
                CaseWritesRepository(run_id).save_work(session, request)
                session.commit()
                return owner
            except ValueError:
                session.rollback()
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(promise, owners))
    winners = [owner for owner in results if owner is not None]
    assert len(winners) == 1
    db_session.expire_all()
    case = db_session.get(Case, case_id)
    assert case.status == "resolved" and case.promised_agent_id == winners[0]


def test_lda_completed_requires_saved_verified_artifacts(db_session, identities, tmp_path, monkeypatch):
    from src.storage.repositories.paragraph import topic_ops
    from src.topic import LDAConfig, LDATrainer

    run = identities[0][0]
    monkeypatch.setattr(topic_ops, "resolve_model_dir", lambda _: tmp_path)
    with pytest.raises(FileNotFoundError):
        topic_ops.insert_topic_model_run(db_session, run.id, num_topics=2)
    db_session.refresh(run)
    assert run.lda_completed is False
    trainer = LDATrainer(LDAConfig(num_topics=2, passes=1, iterations=1))
    trainer.save_model(trainer.train([["山门", "人物"], ["拔剑", "人物"]], filter_extremes=False), tmp_path)
    with pytest.raises(ValueError):
        topic_ops.insert_topic_model_run(db_session, run.id, num_topics=3)
    db_session.refresh(run)
    assert run.lda_completed is False
    topic_ops.insert_topic_model_run(db_session, run.id, num_topics=2)
    db_session.refresh(run)
    assert run.lda_completed is True


def test_w2v_completed_requires_saved_verified_artifacts(db_session, identities, tmp_path, monkeypatch):
    from gensim.models import Word2Vec

    from src.config import paths
    from src.storage.repositories.linguistic_repository import LinguisticRepository

    run = identities[0][0]
    monkeypatch.setattr(paths, "resolve_run_model_dir", lambda *_: tmp_path)
    repo = LinguisticRepository(db_session)
    expected = {"embedding_dimension": 4, "vocabulary_size": 2}
    with pytest.raises(FileNotFoundError):
        repo.insert_word2vec_model_run(run.id, expected)
    db_session.refresh(run)
    assert run.w2v_completed is False
    model = Word2Vec(vector_size=4, min_count=1)
    model.build_vocab([["山门", "人物"]])
    model.save(str(tmp_path / "word2vec.model"))
    with pytest.raises(ValueError):
        repo.insert_word2vec_model_run(run.id, {**expected, "embedding_dimension": 8})
    db_session.refresh(run)
    assert run.w2v_completed is False
    repo.insert_word2vec_model_run(run.id, expected)
    db_session.refresh(run)
    assert run.w2v_completed is True
    assert repo.fetch_word2vec_model_run(run.id).vocabulary_size == 2
