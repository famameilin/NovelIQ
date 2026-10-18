"api main 的具名物理读取"

from __future__ import annotations

from sqlalchemy import text


def api_main_health_check_1(_session):
    return _session.execute(text("SELECT 1"))
