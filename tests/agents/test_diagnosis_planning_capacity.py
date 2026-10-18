"""诊断按会话自治运行：案例会话数=模型并发位，冻结在案例与报告之间

没有派发单元、没有排队、没有逐案例重派尝试；案例会话自行搜索与承诺，报告会话
只读冻结材料。本文件只断言运行结构与旧机制退场，不含内容载荷。
"""

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
        execution_id=new_id(),
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
            execution_id=session_id,
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
        execution_id=session_id,
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


async def test_run_work_orders_case_wave_before_report_wave(monkeypatch):
    calls: list = []

    class Domain:
        def analysis_result(self):
            calls.append("analysis_result")
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

    async def fake_wave(sessions):
        calls.append([f"{key}:{role}" for key, role in sessions])

    monkeypatch.setattr(scheduler, "_wave", fake_wave)
    assert await scheduler._run_work() == "diagnosis-result"
    assert calls == [
        ["case:0:case", "case:1:case"],
        [f"{scheduler.report_key}:report"],
        "analysis_result",
    ]
