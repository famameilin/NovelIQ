"audit recorder 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import AgentToolCall, Execution, ModelCall


def audit_recorder_finish_turn_1(_session, turn_id):
    return _session.get(ModelCall, turn_id)


def audit_recorder_update_turn_timings_1(_session, turn_id):
    return _session.get(ModelCall, turn_id)


def audit_recorder_finish_invocation_1(_session, execution_id):
    return _session.get(Execution, execution_id)


def audit_recorder_ensure_invocation_1(_session, execution_id):
    return _session.get(Execution, execution_id)


def audit_recorder_message_key_call_1(_session, message_key):
    return _session.execute(select(ModelCall.call_id).where(ModelCall.message_key == message_key)).scalar_one_or_none()


def audit_recorder_tool_message_key_call_1(_session, message_key):
    return _session.execute(
        select(AgentToolCall.id).where(AgentToolCall.message_key == message_key)
    ).scalar_one_or_none()
