import pytest

from src.api.dependencies import resolve_run_id
from src.api.exceptions import NovelNotFoundError


class _DummyNovelService:
    def __init__(self, task: dict | None, db_task: dict | None) -> None:
        self._task = task
        self._db_task = db_task

    def get_run_by_task_id(self, task_id: str):
        return self._task

    def _load_task_from_db(self, task_id: str):
        return self._db_task


@pytest.mark.asyncio
async def test_resolve_run_id_uses_in_memory_run_id():
    service = _DummyNovelService(
        task={"task_id": "6b401f00", "run_id": "6b401f00-6d56-4aaa-a05a-95179e8b803a"},
        db_task=None,
    )
    run_id = await resolve_run_id(task_id="6b401f00", novel_service=service)
    assert run_id == "6b401f00-6d56-4aaa-a05a-95179e8b803a"


@pytest.mark.asyncio
async def test_resolve_run_id_fallbacks_to_db_when_in_memory_run_id_missing():
    service = _DummyNovelService(
        task={"task_id": "6b401f00", "novel_id": "2f6b72fc", "status": "completed"},
        db_task={"task_id": "6b401f00", "run_id": "6b401f00-6d56-4aaa-a05a-95179e8b803a"},
    )
    run_id = await resolve_run_id(task_id="6b401f00", novel_service=service)
    assert run_id == "6b401f00-6d56-4aaa-a05a-95179e8b803a"


@pytest.mark.asyncio
async def test_resolve_run_id_raises_not_found_when_task_missing():
    service = _DummyNovelService(task=None, db_task=None)
    with pytest.raises(NovelNotFoundError, match="任务不存在: 6b401f00"):
        await resolve_run_id(task_id="6b401f00", novel_service=service)


@pytest.mark.asyncio
async def test_resolve_run_id_raises_incomplete_when_run_id_missing_everywhere():
    service = _DummyNovelService(
        task={"task_id": "6b401f00", "novel_id": "2f6b72fc", "status": "completed"},
        db_task={"task_id": "6b401f00", "novel_id": "2f6b72fc", "status": "completed"},
    )
    with pytest.raises(NovelNotFoundError, match="任务数据不完整: 6b401f00"):
        await resolve_run_id(task_id="6b401f00", novel_service=service)
