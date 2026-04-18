"""
测试用 Mock 客户端

修改时间: 2026-03-12
修改者: TraeAI
任务: fix-annotation-disambiguation-issues
修改内容:
- 更新 FakeLocalModelClient.annotate_chunk 方法，返回包含新字段的 ChunkAnnotation

修改时间: 2026-04-05
修改者: TraeAI
任务: phase4-code-review-fix
修改内容: 移除已废弃的 relations 和 character_appearances 字段，使用 location_appearances
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.cloud.client import CloudModelClient
from src.models.cloud.schema import CloudAnalysis
from src.models.disambiguation_types import NameCountCandidate
from src.models.local.schema import (
    CharacterSnapshot,
    ChunkAnnotation,
    DialogueSnapshot,
)


class FakeClient(CloudModelClient):
    async def diagnose(self, payload: dict) -> CloudAnalysis:
        return CloudAnalysis(
            novel_id=payload.get("novel_id"),
            foreshadow_rate=0.1,
            arc_scores={"角色0": 8.5, "角色1": 7.0},
            narrative_type="三幕",
            topic_labels=["成长"],
            diagnosis="ok",
            narrative_arc_type="白手起家",
            protagonist="角色0",
            main_characters=["角色0", "角色1"],
            core_cast=["角色0", "角色1"],
        )


class FakeLocalModelClient:
    def __init__(self) -> None:
        self._call_count = 0
        self._config = type("Config", (), {"model": "test-model"})()
        self._session = None
        self._novel_id = None
        self._token_usage_callback = None

    def set_session(self, session) -> None:
        self._session = session

    def set_runtime_context(self, novel_id, token_usage_callback) -> None:
        self._novel_id = novel_id
        self._token_usage_callback = token_usage_callback

    def annotate_chunk(
        self,
        text: str,
        prev_summary: str | None = None,
        alias_map: dict[str, str] | None = None,
        chunk_id: int | None = None,
        global_context: str | None = None,
        prev_tail_text: str | None = None,
        active_entities: str | None = None,
    ) -> ChunkAnnotation:
        self._call_count += 1
        characters = [
            CharacterSnapshot(
                name="张三",
                role_function="protagonist",
                action="测试行为",
                emotion="平静",
                emotion_score=0,
            )
        ]
        dialogues = [
            DialogueSnapshot(speaker="张三", tone="温和"),
        ]
        return ChunkAnnotation(
            emotional_valence="neutral",
            event_type="日常",
            pivot_moment=False,
            cliffhanger=False,
            has_foreshadowing=False,
            foreshadowing_type=None,
            foreshadowing_desc="",
            characters=characters,
            dialogues=dialogues,
            location_appearances=[],
            chunk_summary="",
        )

    def disambiguate_characters(
        self,
        candidates: list[NameCountCandidate],
        context_sentences: dict[str, str] | None = None,
        existing_names: list[str] | None = None,
        prompt_context=None,
    ) -> dict[str, str]:
        result = {}
        for item in candidates:
            name = item["name"]
            if name == "张三丰":
                result[name] = "张三"
            else:
                result[name] = name
        return result
