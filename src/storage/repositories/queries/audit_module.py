"audit module 的具名物理读取"

from __future__ import annotations

from sqlalchemy import select

from src.storage.models import AgentLoop, ToolCall


def audit_module_skip_replayed_1(_session, message_message_id):
    return _session.execute(
        select(AgentLoop.id).where(AgentLoop.message_key == message_message_id)
    ).scalar_one_or_none()


def audit_module_skip_replayed_2(_session, message_message_id):
    return _session.execute(select(ToolCall.id).where(ToolCall.message_key == message_message_id)).scalar_one_or_none()
