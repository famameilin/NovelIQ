"""
测试用 Mock 客户端

修改时间: 2026-03-12
修改者: TraeAI
任务: fix-annotation-disambiguation-issues
修改内容: 
- 更新 FakeLocalModelClient.annotate_chunk 方法，返回包含 character_appearances 和 chunk_summary 新字段的 ChunkAnnotation
"""
import sys
from pathlib import Path
from typing import Dict, List

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.cloud.client import CloudModelClient
from src.models.cloud.schema import CloudAnalysis
from src.models.local.unified_client import UnifiedModelClient
from src.models.local.schema import (
    ChunkAnnotation,
    CharacterSnapshot,
    DialogueSnapshot,
    RelationChangeSnapshot,
)


class FakeClient(CloudModelClient):
    def diagnose(self, payload: dict) -> CloudAnalysis:
        return CloudAnalysis(
            novel_id=payload.get("novel_id"),
            foreshadow_rate=0.1,
            arc_scores=[0.1],
            narrative_type="三幕",
            topic_labels=["成长"],
            diagnosis="ok",
        )


class FakeLocalModelClient(UnifiedModelClient):
    def __init__(self) -> None:
        self._call_count = 0

    def annotate_chunk(
        self,
        text: str,
        prev_summary: str | None = None,
        alias_map: Dict[str, str] | None = None,
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
        relations = [
            RelationChangeSnapshot(
                from_name="张三",
                to_name="李四",
                type="盟友",
                change="新建",
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
            relations=relations,
            dialogues=dialogues,
            character_appearances=[],
            chunk_summary="",
        )

    def disambiguate_characters(
        self,
        candidates: List[str],
        context_sentences: Dict[str, str] | None = None,
        existing_names: List[str] | None = None,
    ) -> Dict[str, str]:
        result = {}
        for name in candidates:
            if name == "张三丰":
                result[name] = "张三"
            else:
                result[name] = name
        return result
