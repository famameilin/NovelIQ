"""诊断完成检查回执：身份段与结构段的缺口一次列全全部未满足义务

run 52cbb1ac 第 9 轮实证：工作 68fb7951 第 9 回合 finish 只收到一条比较缺口
（raise-first 逐条抛），补掉后第 10 回合又被下一条挡住，回合预算耗尽失败
budget_exhausted。回执必须覆盖当前全部未满足义务，模型才能在一份程序内批量补齐；
同一来源的缺失比较还必须聚合为一条并列出全部更晚目标。
"""

import json

import pytest

from src.agents.annotation.agent import AnnotationAgent
from src.agents.diagnosis.domain import DiagnosisDomain
from src.event_bus import EventBus
from src.event_trees.organization import EventOrganizationDraft
from tests.agents.test_complete_event_work import execution_for, save_and_confirm
from tests.agents.test_diagnosis_program import (
    declaration_case as declaration_case,  # noqa: F401
)
from tests.support.chapter_annotation_helpers import create_run_with_chunks

# 引文锚点决定事件正文位置："顾霜寻路" 在前、"点灯" 在后，
# 结构配对义务因此确定地落到更早事件的责任工作
_FIRST_IDENTITY = (
    'page = search_events(limit=20)\n'
    'write_event(items=[{"operation":"identity", "key":"寻路", "title":"寻路", "problem":"能否找到路", '
    '"summary":"顾霜寻路", "event_type":"寻路", "status":"ongoing", '
    '"declaration_ids":[page["events"][0]["declaration_id"]], '
    '"stage_order":[page["events"][0]["declaration_id"]], '
    '"current_declaration_id":page["events"][0]["declaration_id"], "reason":"依据本章原文声明核对", '
    '"evidence":[{"paragraph_id":0, "quote":"顾霜寻路"}]}])\n'
    'write_event(items=[{"operation":"declaration_review", '
    '"declaration_ids":[page["events"][0]["declaration_id"]], "reason":"按本章原文逐段核对"}])\n'
    'write_event(items=[{"operation":"compare", "source_declaration_id":page["events"][0]["declaration_id"], '
    '"target_declaration_ids":[page["events"][1]["declaration_id"]], "disposition":"independent", '
    '"reason":"寻路和照明各有独立问题", "evidence":[{"paragraph_id":0}]}])\n'
)
_SECOND_IDENTITY = (
    'page = search_events(limit=20)\n'
    'write_event(items=[{"operation":"identity", "key":"点灯", "title":"点灯", "problem":"能否照明", '
    '"summary":"顾霜点灯", "event_type":"照明", "status":"resolved", '
    '"declaration_ids":[page["events"][1]["declaration_id"]], '
    '"stage_order":[page["events"][1]["declaration_id"]], '
    '"current_declaration_id":page["events"][1]["declaration_id"], "reason":"依据本章原文声明核对", '
    '"evidence":[{"paragraph_id":0, "quote":"点灯"}]}])\n'
    'write_event(items=[{"operation":"declaration_review", '
    '"declaration_ids":[page["events"][1]["declaration_id"]], "reason":"按本章原文逐段核对"}])\n'
)


class _Observer:
    """按派发轮次提供执行身份；生产由审计观察者提供同一组字段"""

    def __init__(self, name: str, attempt: int) -> None:
        self.invocation_id = name
        self._context = {"execution_id": name, "attempt_number": attempt}

    def record_tool_call(self, *args: object, **kwargs: object) -> None:
        pass


def _domain(draft) -> DiagnosisDomain:
    return DiagnosisDomain(
        session=draft.session,
        run_id=draft.run_id,
        novel_id="test-novel",
        execution_id=f"receipt-{draft.run_id[:8]}",
        novel_title=None,
        model_id="test-model",
    )


@pytest.fixture
async def three_declarations(db_session):
    novel_id, run_id = create_run_with_chunks(db_session, texts=["顾霜寻路，点灯，又在城门口遇见旧人。"])
    agent = AnnotationAgent(EventBus(), run_id, lambda: db_session, novel_id=novel_id)
    execution, program = execution_for(agent, db_session, 1)
    receipt = json.loads(
        await program.execute(
            'event(el="a", title="寻路", problem="能否找到路", summary="顾霜寻路", '
            'event_type="寻路", status="ongoing", evidence=1)\n'
            'event(el="b", title="点灯", problem="能否照明", summary="顾霜点灯", '
            'event_type="照明", status="resolved", evidence=1)\n'
            'event(el="c", title="重逢", problem="能否相认", summary="顾霜遇旧人", '
            'event_type="重逢", status="ongoing", evidence=1)'
        )
    )
    assert not receipt.get("failed"), receipt
    await save_and_confirm(agent, db_session, execution)
    draft = EventOrganizationDraft(db_session, run_id, "program-fixture")
    draft.work_id, draft.producer_invocation_id = "program-fixture", "program-fixture"
    yield draft
    agent.close()


def test_identity_receipt_aggregates_all_missing_targets_in_one_call(three_declarations):
    domain = _domain(three_declarations)
    try:
        sources = list(domain.sources)
        assert len(sources) == 3
        work = domain.initial_work()[0]
        context = domain.build_context(work, "identity", _Observer("receipt-identity", 1), None)
        gaps = context.completion_check()
        # 同一来源的缺失比较是一条回执，列出全部更晚目标
        comparison = [line for line in gaps if line.startswith("来源比较尚未明确判断")]
        assert len(comparison) == 1
        for target in sources[1:]:
            assert target in comparison[0]
        # 声明核对与身份判断缺口与比较缺口同批列出
        assert [line for line in gaps if line.startswith("声明缺少事实核对")]
        assert [line for line in gaps if line.startswith("声明缺少身份判断")]
        assert len(gaps) == 3
    finally:
        domain.close()


async def test_structure_receipt_lists_every_gap_in_one_call(declaration_case):
    domain = _domain(declaration_case)
    try:
        first, second = domain.initial_work()
        first_identity = domain.build_context(first, "identity", _Observer("receipt-a", 1), None)
        assert not json.loads(await first_identity.program.execute(_FIRST_IDENTITY)).get("failed")
        second_identity = domain.build_context(second, "identity", _Observer("receipt-b", 1), None)
        assert not json.loads(await second_identity.program.execute(_SECOND_IDENTITY)).get("failed")
        # 前置条件：身份段义务已全部满足，结构段回执只列结构缺口
        assert first_identity.completion_check() == []
        assert second_identity.completion_check() == []

        structure = domain.build_context(first, "structure", _Observer("receipt-c", 2), None)
        gaps = structure.completion_check()
        own = next(
            item for item in domain.draft.events.values() if item.source_work_id == first.work_id
        )
        other = next(item for item in domain.draft.events.values() if item.event_id != own.event_id)
        pair = tuple(sorted((own.event_id, other.event_id)))
        reviews = [line for line in gaps if line.startswith("事件结构须核对实际版本")]
        endpoints = [line for line in gaps if line.startswith("已派发结构事项须明确处置实际版本")]
        assert len(reviews) == 1 and own.event_id in reviews[0]
        assert len(endpoints) == 1 and str(pair) in endpoints[0]
        assert len(gaps) == 2
    finally:
        domain.close()
