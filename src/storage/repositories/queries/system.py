"""system 的固定 SQL 记录查询"""

from __future__ import annotations

from sqlalchemy import text


def check_connection(_session):
    return _session.execute(text("SELECT 1"))
