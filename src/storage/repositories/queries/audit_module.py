"从 src/audit/module.py 分离的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import AgentToolCall, ModelCall


def audit_module_skip_replayed_1(_session, message_message_id):
    return _session.execute(
        select(ModelCall.call_id).where(ModelCall.message_key == message_message_id)
    ).scalar_one_or_none()


def audit_module_skip_replayed_2(_session, message_message_id):
    return _session.execute(
        select(AgentToolCall.id).where(AgentToolCall.message_key == message_message_id)
    ).scalar_one_or_none()
