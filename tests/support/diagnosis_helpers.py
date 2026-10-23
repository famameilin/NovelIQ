"""读取夹具显式提交声明身份判断，沿正式保存链建立新结果"""

from src.event_trees.organization import EventOrganizationDraft
from src.storage import new_id
from src.storage.models import Agent
from src.storage.repositories.diagnosis_event_writes import save_diagnosis_events
from src.storage.repositories.organization_writes import save_organization
from tests.support.storage_fixtures import storage_for

from .event_tree_fixtures import report_case_anchor


def declaration_event_draft(session, run_id, *, groups=None):
    """夹具显式指定声明身份分组，未指定时各项独立，不按旧树推断"""
    session_id = new_id()
    agent_id = new_id()
    session.add(Agent(id=session_id, run_id=run_id, type="report", status="running"))
    session.add(Agent(id=agent_id, run_id=run_id, type="report", status="running"))
    draft = EventOrganizationDraft(storage_for(session), run_id, session_id)
    draft.fixture_session = session
    draft.case_id = report_case_anchor(run_id)
    draft.producer_agent_id = agent_id
    from src.event_trees.diagnosis_persistence import hydrate_draft_from_run

    hydrate_draft_from_run(storage_for(session), run_id, draft)
    return draft


def persist_event_draft(session, draft, report_id=None):
    """按正式保存入口写报告、完整事件与叙事组织；report_id 缺省时本夹具先建报告"""
    organization = draft.finish()
    if report_id is None:
        from src.diagnosis.schema import AgentAnalysis
        from tests.support.storage_fixtures import insert_report_fixture

        report_id = insert_report_fixture(
            session,
            draft.run_id,
            str(draft.agent_id),
            AgentAnalysis(narrative_organization=organization),
        )
    save_diagnosis_events(session, draft.run_id, organization, report_id)
    save_organization(session, draft.run_id, organization, report_id)
    session.flush()
    return report_id
