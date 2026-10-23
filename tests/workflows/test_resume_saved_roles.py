"""恢复规划保留已保存角色，仅补齐缺失工作"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.config import settings
from src.work.policy import LANES
from src.workflows import annotate


@pytest.fixture
def resume_inputs(monkeypatch):
    states = [
        SimpleNamespace(chapter_id=1, state="saved", role="annotation"),
        SimpleNamespace(chapter_id=2, state="saved", role="event"),
    ]
    chapters = [
        SimpleNamespace(chapter_id=1, sequence=1, text="短", display_index_label="一"),
        SimpleNamespace(chapter_id=2, sequence=2, text="长章原文。", display_index_label="二"),
    ]
    storage = SimpleNamespace(reads=SimpleNamespace(
        workflows_annotate_load_work_1=lambda _: chapters,
        workflows_annotate_load_work_2=lambda chapter, _: [SimpleNamespace(
            chapter_id=chapter.chapter_id, paragraph_id=chapter.chapter_id,
            local_start_char=0, text=chapter.text,
        )],
    ))
    monkeypatch.setattr(annotate, "fetch_annotation_role_records", lambda *_: list(states))
    return storage, states


@pytest.mark.parametrize("threshold", [2, 100])
@pytest.mark.parametrize("kept", [{"event"}, {"entity"}, {"event", "metric"}])
def test_load_and_plan_keep_saved_roles_across_threshold_changes(resume_inputs, monkeypatch, threshold, kept):
    storage, states = resume_inputs
    states[1:] = [SimpleNamespace(chapter_id=2, state="saved", role=role) for role in kept]
    monkeypatch.setattr(settings.models.annotation, "sub_chunk_max_chars", threshold)
    work, complete, saved = annotate._load_work(lambda: storage, "run")
    planned, rebuild = annotate._plan_work(work, saved)
    assert complete == {1}
    assert rebuild == []
    assert {item.payload["role"] for item in work} == set(LANES)
    assert {item.payload["role"] for item in planned} == set(LANES) - kept
    assert all(item.payload["chapter_id"] == 2 for item in planned)


async def test_resume_runs_only_missing_roles_and_never_discards_saved_chapter(resume_inputs, monkeypatch):
    storage, states = resume_inputs
    monkeypatch.setattr(settings.models.annotation, "sub_chunk_max_chars", 100)
    monkeypatch.setattr(annotate, "get_storage_factory", lambda: lambda: storage)
    monkeypatch.setattr(annotate, "eligible_chapters", lambda *_: set())
    agent = SimpleNamespace(address="annotation", close=Mock())
    audit = SimpleNamespace(address="audit", close=AsyncMock())
    activity = SimpleNamespace(close=Mock())
    monkeypatch.setattr(annotate, "AnnotationAgent", lambda *_args, **_kwargs: agent)
    monkeypatch.setattr(annotate, "AuditModule", lambda *_: audit)
    monkeypatch.setattr(annotate, "ActivityRelay", lambda *_: activity)
    bus = SimpleNamespace(request=AsyncMock())
    dispatched = []

    class Pool:
        def __init__(self, **kwargs):
            pass

        async def run(self, work, **kwargs):
            dispatched.extend(work)
            for receipt in work:
                states.append(SimpleNamespace(chapter_id=2, state="saved", role=receipt.payload["role"]))
                await kwargs["on_saved"](receipt)

    monkeypatch.setattr(annotate, "ChapterWorkerPool", Pool)
    retained_event = states[1]
    assert await annotate.run_annotate("run", storage, bus=bus) == (2, 0, 2)
    assert {item.payload["role"] for item in dispatched} == {"entity", "metric"}
    assert states[1] is retained_event
    recovery = [call.args[0] for call in bus.request.await_args_list if call.args[0].topic == "agent.recover"]
    assert len(recovery) == 1 and recovery[0].payload["chapter_ids"] == []
    assert not any(message.payload.get("mode") == "chapter_reset" for message in recovery)
    agent.close.assert_called_once()
    audit.close.assert_awaited_once()
