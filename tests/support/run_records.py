"""测试夹具的运行记录状态构造，不向生产仓储追加旧接口"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.storage.models import Run


def set_run_status(session: Session, run_id: str, status: str) -> None:
    run = session.get(Run, run_id)
    if run is None:
        return
    now = datetime.now(UTC).replace(tzinfo=None)
    run.status = status
    if status in {"completed", "failed", "cancelled"}:
        run.completed_at = now
    run.updated_at = now
    session.commit()
