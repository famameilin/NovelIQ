"""切分只保留事件边界（2026-10-15 用户裁定「不要预算，要切分」「切分不要使用max_tokens」）

token 容量语义已死：本文件只断言结构——每个声明一个案例单元、收尾单报告单元、
派发面不再存在任何计量/比率闸门，规划模块整体退场。
"""

import pytest

from src.agents.diagnosis.domain import DiagnosisDomain
from tests.agents.test_diagnosis_program import declaration_case as declaration_case  # noqa: F401


@pytest.fixture
def domain(declaration_case):
    draft = declaration_case
    result = DiagnosisDomain(session=draft.session, run_id=draft.run_id, novel_id="test-novel",
                             execution_id=f"structure-{draft.run_id[:8]}", novel_title=None,
                             model_id="test-model")
    yield result
    result.close()


def test_one_case_unit_per_declaration(domain):
    units = domain.initial_work()
    assert [unit.responsible_ids for unit in units] == [(identifier,) for identifier in domain.sources]
    assert all(unit.role == "case" for unit in units)
    for unit in units:
        assert set(unit.input_payload) == {"source_hash", "event_ids"}
        assert unit.input_payload["event_ids"] == list(unit.responsible_ids)
        assert unit.input_payload["source_hash"] == domain.source_hash
        # 案例 payload 不含目录、比较对或全量材料
        assert "catalog" not in unit.input_payload and "comparison_pairs" not in unit.input_payload


def test_initial_work_is_deterministic_and_registry_mirrors(domain):
    first = [(unit.case_id, unit.responsible_ids, unit.input_payload) for unit in domain.initial_work()]
    second = [(unit.case_id, unit.responsible_ids, unit.input_payload) for unit in domain.initial_work()]
    assert first == second
    assert all(unit.case_id in domain.units for unit in domain.initial_work())


def test_no_numeric_planning_machinery_remains(domain):
    for name in ("_measure", "_fits_work", "_pack_work", "_partition", "_request_size", "_check_messages",
                 "input_limit", "output_limit", "tool_overhead"):
        assert not hasattr(domain, name)
    # 规划模块已整体退场：不存在第二套切分/计量入口
    import importlib.util

    assert importlib.util.find_spec("src.agents.diagnosis.work_planning") is None


def test_finishing_is_single_report_unit(domain):
    domain.initial_work()
    finishing = domain.finishing_work()
    assert len(finishing) == 1
    unit = finishing[0]
    assert unit.role == "report"
    event_ids = [item.event_id for item in domain.draft.events.values()]
    assert unit.responsible_ids == tuple(event_ids)
    assert set(unit.input_payload) == {"structure_snapshot", "catalog", "arcs", "outcomes"}
    assert [row["event_id"] for row in unit.input_payload["catalog"]] == event_ids


def test_create_diagnosis_domain_only_resolves_pool_entry(declaration_case, monkeypatch):
    from src.agents.diagnosis import domain as domain_module
    from src.config import settings
    from src.config.schemas.model import WeightedModelSettings

    draft = declaration_case
    session_id = f"capacity-entry-{draft.run_id[:8]}"
    monkeypatch.setattr(settings.models, "diagnosis_model_id", "not-in-pool-model")
    with pytest.raises(ValueError, match="诊断模型不在模型池中"):
        domain_module.create_diagnosis_domain(
            session=draft.session, run_id=draft.run_id, novel_id="test-novel",
            execution_id=session_id, novel_title=None,
        )
    # 存在条目时以声明 model_id 建域，不读取任何窗口/容量数字
    monkeypatch.setattr(
        settings.models, "model_pool",
        [WeightedModelSettings("cap-model", "https://cap.example/v1", "cap-key")],
    )
    monkeypatch.setattr(settings.models, "diagnosis_model_id", "cap-model")
    created = domain_module.create_diagnosis_domain(
        session=draft.session, run_id=draft.run_id, novel_id="test-novel",
        execution_id=session_id, novel_title=None,
    )
    assert created.model_id == "cap-model"
    assert not hasattr(created, "input_limit") and not hasattr(created, "output_limit")
    created.close()


def test_dispatch_execution_identity_is_minted_per_episode() -> None:
    """执行身份按派发轮次铸造：同一轮内稳定、跨轮（续跑）不同（2026-10-17 run 52cbb1ac）

    审计契约是每个真实 invocation 一条终态行（executions 的 invocation 形状）；续跑
    重派必须以新身份与新尝试序号收口，否则第一个案例收口就会撞"已结束，不能按
    不同结果重复收口"。身份按案例一次定终身的旧形态已被本用例锁死。
    """
    from src.agents.diagnosis.work_runtime import CaseUnit, DiagnosisWorkScheduler
    from src.event_bus import EventBus

    unit = CaseUnit("decl-1", "case", ("decl-1",), {"source_hash": "h", "event_ids": ["decl-1"]})

    class _AttemptSource:
        def __init__(self, attempt: int) -> None:
            self.attempt = attempt

        def next_dispatch_attempt(self, case_id: str) -> int:
            return self.attempt

    def make_scheduler(attempt: int) -> DiagnosisWorkScheduler:
        return DiagnosisWorkScheduler(
            run_id="run-episode",
            domain=_AttemptSource(attempt),  # type: ignore[arg-type]
            bus=EventBus(),
            model_id="test-model",
            llm_factory=lambda _model_id: None,
            observer_factory=lambda _progress: None,
            audit_barrier=lambda: None,
        )

    first_episode, second_episode = make_scheduler(1), make_scheduler(2)
    # 同一轮内多次取状态：身份与尝试序号稳定
    assert first_episode._state(unit).execution_id == first_episode._state(unit).execution_id
    assert first_episode._state(unit).dispatch_attempt == 1
    # 新一轮派发：新执行身份、新尝试序号
    assert first_episode._state(unit).execution_id != second_episode._state(unit).execution_id
    assert second_episode._state(unit).dispatch_attempt == 2


def test_next_dispatch_attempt_accumulates_across_episodes(declaration_case) -> None:
    """尝试序号跨轮累计：该案例既有执行事实数 + 1（2026-10-17 run 52cbb1ac）

    登记契约要求 (案例, 角色, 尝试) 唯一（"该次尝试已有真实执行"）：续跑重派若不推进
    序号，新一轮登记直接被拒、整轮失败。
    """
    from uuid import uuid4

    from src.event_trees.organization import register_diagnosis_execution

    draft = declaration_case
    session_id = f"attempts-{draft.run_id[:8]}"
    # 会话行由领域构造器的短事务登记；测试侧不预登记，避免与外层未提交行互相等锁
    instance = DiagnosisDomain(
        session=draft.session, run_id=draft.run_id, novel_id="test-novel",
        execution_id=session_id, novel_title=None, model_id="test-model",
    )
    try:
        case_id = instance.initial_work()[0].case_id
        assert instance.next_dispatch_attempt(case_id) == 1
        register_diagnosis_execution(
            draft.session, run_id=draft.run_id, execution_id=f"exec-{uuid4().hex[:12]}",
            role="case", case_anchor=case_id, attempt_number=1,
        )
        assert instance.next_dispatch_attempt(case_id) == 2
    finally:
        instance.close()
