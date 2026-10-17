"""切分只保留事件边界（2026-10-15 用户裁定「不要预算，要切分」「切分不要使用max_tokens」）

token 容量语义已死：本文件只断言结构——每个声明一个事件工作、收尾单报告工作、
规划机器不再存在任何计量/比率闸门。
"""

import pytest

from src.agents.diagnosis.domain import DiagnosisDomain
from src.agents.diagnosis.work_planning import CONTRACT_VERSION, WorkSpec
from tests.agents.test_diagnosis_program import declaration_case as declaration_case  # noqa: F401


@pytest.fixture
def domain(declaration_case):
    draft = declaration_case
    result = DiagnosisDomain(session=draft.session, run_id=draft.run_id, novel_id="test-novel",
                             execution_id=f"structure-{draft.run_id[:8]}", novel_title=None,
                             model_id="test-model")
    yield result
    result.close()


def test_one_event_work_per_declaration(domain):
    works = domain.initial_work()
    assert [work.responsible_ids for work in works] == [(identifier,) for identifier in domain.sources]
    assert all(work.role == "event" for work in works)
    for work in works:
        assert set(work.input_payload) == {"source_hash", "event_ids"}
        assert work.input_payload["event_ids"] == list(work.responsible_ids)
        assert work.input_payload["source_hash"] == domain.source_hash
        # 事件声明 payload 不含目录、比较对或全量材料
        assert "catalog" not in work.input_payload and "comparison_pairs" not in work.input_payload


def test_initial_work_is_deterministic_and_registry_mirrors(domain):
    first = [
        (work.work_id, work.input_hash, work.responsible_ids) for work in domain.initial_work()
    ]
    second = [(work.work_id, work.input_hash, work.responsible_ids) for work in domain.initial_work()]
    assert first == second
    assert all(work.work_id in domain.work for work in domain.initial_work())


def test_no_numeric_planning_machinery_remains(domain):
    for name in ("_measure", "_fits_work", "_pack_work", "_partition", "_request_size", "_check_messages",
                 "input_limit", "output_limit", "tool_overhead"):
        assert not hasattr(domain, name)
    import src.agents.diagnosis.work_planning as planning

    assert not hasattr(planning, "partition_materials")


def test_finishing_is_single_report_work(domain):
    domain.initial_work()
    finishing = domain.finishing_work()
    assert len(finishing) == 1
    work = finishing[0]
    assert work.role == "report"
    event_ids = [item.event_id for item in domain.draft.events.values()]
    assert work.responsible_ids == tuple(event_ids)
    assert set(work.input_payload) == {"structure_snapshot", "catalog", "arcs", "outcomes"}
    assert [row["event_id"] for row in work.input_payload["catalog"]] == event_ids


def test_work_contract_version_is_the_v2_event_pool_contract():
    assert CONTRACT_VERSION == "event-tree-declarations-v2"


def test_spec_identity_changes_with_payload(domain):
    identifiers = list(domain.sources)
    first = WorkSpec(domain.run_id, "event", (identifiers[0],),
                     {"source_hash": domain.source_hash, "event_ids": [identifiers[0]]})
    second = WorkSpec(domain.run_id, "event", (identifiers[0],),
                      {"source_hash": domain.source_hash, "event_ids": [identifiers[0]],
                       "corrections": {"field": "identity"}})
    assert first.work_id != second.work_id
    assert first.input_hash != second.input_hash


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

    审计契约是每个真实 invocation 一条终态行（executions 的 work 尝试形状）；续跑
    重派必须以新身份与新尝试序号收口，否则第一个 work 收口就会撞"已结束，不能按
    不同结果重复收口"。身份按 work 一次定终身的旧形态已被本用例锁死。
    """
    from src.agents.diagnosis.work_runtime import DiagnosisWorkScheduler
    from src.event_bus import EventBus

    work = WorkSpec("run-episode", "event", ("decl-1",), {"source_hash": "h", "event_ids": ["decl-1"]})

    class _AttemptSource:
        def __init__(self, attempt: int) -> None:
            self.attempt = attempt

        def next_dispatch_attempt(self, work_id: str) -> int:
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
    assert first_episode._state(work).execution_id == first_episode._state(work).execution_id
    assert first_episode._state(work).dispatch_attempt == 1
    # 新一轮派发：新执行身份、新尝试序号
    assert first_episode._state(work).execution_id != second_episode._state(work).execution_id
    assert second_episode._state(work).dispatch_attempt == 2


def test_next_dispatch_attempt_accumulates_across_episodes(declaration_case) -> None:
    """尝试序号跨轮累计：该 work 既有执行事实数 + 1（2026-10-17 run 52cbb1ac）

    登记契约要求 (work, attempt) 唯一（"该次尝试已有真实执行"）：续跑重派若不推进
    序号，新一轮登记直接被拒、整轮失败。
    """
    from uuid import uuid4

    from src.event_trees.organization import register_diagnosis_execution, register_diagnosis_work

    draft = declaration_case
    session_id = f"attempts-{draft.run_id[:8]}"
    work_id = f"work-{uuid4().hex[:12]}"
    # 会话行由领域构造器的短事务登记；测试侧不预登记，避免与外层未提交行互相等锁
    instance = DiagnosisDomain(
        session=draft.session, run_id=draft.run_id, novel_id="test-novel",
        execution_id=session_id, novel_title=None, model_id="test-model",
    )
    try:
        register_diagnosis_work(draft.session, session_id=session_id, work_id=work_id, role="event")
        assert instance.next_dispatch_attempt(work_id) == 1
        register_diagnosis_execution(
            draft.session, work_id=work_id, execution_id=f"exec-{uuid4().hex[:12]}", attempt_number=1
        )
        assert instance.next_dispatch_attempt(work_id) == 2
    finally:
        instance.close()
