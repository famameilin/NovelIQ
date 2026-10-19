"""诊断按会话自治运行：案例会话数=模型并发位，案例池归零后才进入报告

没有派发单元、没有排队：案例池未归零就按波次继续派发案例会话，每波会话用尽
配置回合即结束；报告会话只读冻结材料。本文件只断言运行结构与旧机制退场，不含内容载荷。
"""

import asyncio

import pytest

from src.agents.diagnosis.domain import DiagnosisDomain
from src.agents.diagnosis.work_runtime import DiagnosisWorkScheduler
from src.event_bus import EventBus
from src.storage import new_id
from tests.agents.test_diagnosis_program import declaration_case as declaration_case  # noqa: F401
from tests.support.storage_fixtures import fixture_id, storage_for


@pytest.fixture
def domain(declaration_case):
    draft = declaration_case
    result = DiagnosisDomain(
        session=storage_for(draft.fixture_session),
        run_id=draft.run_id,
        novel_id=fixture_id(__name__, "test-novel"),
        agent_id=new_id(),
        novel_title=None,
        model_id="test-model",
    )
    yield result
    result.close()


def test_no_planning_or_dispatch_machinery_remains(domain):
    for name in (
        "_measure",
        "_fits_work",
        "_pack_work",
        "_partition",
        "_request_size",
        "_check_messages",
        "input_limit",
        "output_limit",
        "tool_overhead",
        "initial_work",
        "finishing_work",
        "next_dispatch_attempt",
        "units",
    ):
        assert not hasattr(domain, name)
    # 不存在第二套切分/计量入口
    import importlib.util

    assert importlib.util.find_spec("src.agents.diagnosis.work_planning") is None


def test_create_diagnosis_domain_only_resolves_pool_entry(declaration_case, monkeypatch):
    from src.agents.diagnosis import domain as domain_module
    from src.config import settings
    from src.config.schemas.model import WeightedModelSettings

    draft = declaration_case
    session_id = new_id()
    monkeypatch.setattr(settings.models, "diagnosis_model_id", "not-in-pool-model")
    with pytest.raises(ValueError, match="诊断模型不在模型池中"):
        domain_module.create_diagnosis_domain(
            session=storage_for(draft.fixture_session),
            run_id=draft.run_id,
            novel_id=fixture_id(__name__, "test-novel"),
            agent_id=session_id,
            novel_title=None,
        )
    # 存在条目时以声明 model_id 建域，不读取任何窗口/容量数字
    monkeypatch.setattr(
        settings.models,
        "model_pool",
        [WeightedModelSettings("cap-model", "https://cap.example/v1", "cap-key")],
    )
    monkeypatch.setattr(settings.models, "diagnosis_model_id", "cap-model")
    created = domain_module.create_diagnosis_domain(
        session=storage_for(draft.fixture_session),
        run_id=draft.run_id,
        novel_id=fixture_id(__name__, "test-novel"),
        agent_id=session_id,
        novel_title=None,
    )
    assert created.model_id == "cap-model"
    assert not hasattr(created, "input_limit") and not hasattr(created, "output_limit")
    created.close()


def test_case_session_count_follows_model_in_flight(monkeypatch):
    from src.config import settings
    from src.config.schemas.model import WeightedModelSettings

    monkeypatch.setattr(
        settings.models,
        "model_pool",
        [WeightedModelSettings("diag-model", "https://x.example/v1", "k", max_in_flight=3)],
    )

    def build(**overrides):
        params = {
            "run_id": fixture_id(__name__, "run"),
            "domain": None,
            "bus": EventBus(),
            "model_id": "diag-model",
            "llm_factory": lambda _model_id: None,
            "observer_factory": lambda _progress: None,
            "audit_barrier": lambda: None,
        }
        params.update(overrides)
        return DiagnosisWorkScheduler(**params)

    assert build().case_sessions == 3
    # 显式覆盖优先（测试与离线演练）
    assert build(case_sessions=5).case_sessions == 5


async def test_run_work_refills_case_sessions_continuously_until_pool_empty(monkeypatch):
    started: list = []
    completed: list = []
    counts = {"pending": 3, "resolved": 0}

    class Domain:
        def case_counts(self):
            return counts["pending"], counts["resolved"]

        def analysis_result(self):
            return "diagnosis-result"

    scheduler = DiagnosisWorkScheduler(
        run_id=fixture_id(__name__, "run"),
        domain=Domain(),
        bus=EventBus(),
        model_id="m",
        llm_factory=lambda _model_id: None,
        observer_factory=lambda _progress: None,
        audit_barrier=lambda: None,
        case_sessions=2,
    )

    async def fake_session(key, role):
        started.append(f"{key}:{role}")
        await asyncio.sleep(0.05 if key == "case:2" else 0.01)
        if counts["pending"] > 0:
            counts["pending"] -= 1
            counts["resolved"] += 1
        completed.append(key)

    async def fake_wave(sessions):
        started.append([f"{key}:{role}" for key, role in sessions])

    monkeypatch.setattr(scheduler, "_session", fake_session)
    monkeypatch.setattr(scheduler, "_wave", fake_wave)
    assert await scheduler._run_work() == "diagnosis-result"
    # 并发位一空立即补位：第三个会话在第二个慢会话结束前就已完成，不存在整批等齐
    assert completed.index("case:3") < completed.index("case:2")
    assert started[-1] == [f"{scheduler.report_key}:report"]
    assert counts["pending"] == 0


async def test_run_work_skips_case_sessions_when_pool_is_empty(monkeypatch):
    started: list = []

    class Domain:
        def case_counts(self):
            return 0, 5

        def analysis_result(self):
            return "diagnosis-result"

    scheduler = DiagnosisWorkScheduler(
        run_id=fixture_id(__name__, "run"),
        domain=Domain(),
        bus=EventBus(),
        model_id="m",
        llm_factory=lambda _model_id: None,
        observer_factory=lambda _progress: None,
        audit_barrier=lambda: None,
        case_sessions=2,
    )

    async def fake_session(key, role):
        started.append(f"{key}:{role}")

    async def fake_wave(sessions):
        started.append([f"{key}:{role}" for key, role in sessions])

    monkeypatch.setattr(scheduler, "_session", fake_session)
    monkeypatch.setattr(scheduler, "_wave", fake_wave)
    assert await scheduler._run_work() == "diagnosis-result"
    assert started == [[f"{scheduler.report_key}:report"]]
