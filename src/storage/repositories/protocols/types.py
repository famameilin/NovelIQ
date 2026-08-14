"""
Repository protocol 语义类型

为协议层提供命名 DTO，避免继续暴露过宽的动态类型与无语义裸结构返回值
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

type RepositoryScalar = str | int | float | bool | None
type RepositoryValue = RepositoryScalar | list[object] | dict[str, object]
type RepositoryRecord = dict[str, RepositoryValue]

type AnnotationRecord = RepositoryRecord
type CloudAnalysisRecord = RepositoryRecord
type TokenUsageStatsRecord = RepositoryRecord


class RunRecord(TypedDict, total=False):
    """运行记录协议 DTO"""

    run_id: str
    novel_id: str
    source_path: str | None
    title: str | None
    author: str | None
    status: str
    progress: float | None
    stage: str | None
    sub_stage: str | None
    current: int | None
    total: int | None
    message: str | None
    error: str | None
    task_kind: str
    request_payload: dict[str, RepositoryValue] | None
    cancel_requested: bool
    worker_id: str | None
    heartbeat_at: str | None
    completed_at: str | None
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class ChunkTextRow:
    """分块文本行"""

    chunk_id: int
    text: str


@dataclass(frozen=True, slots=True)
class ChunkCounts:
    """分块统计结果"""

    total_chunks: int
    total_chars: int


@dataclass(frozen=True, slots=True)
class GlobalStatValue:
    """全局统计写入/读取行"""

    stat_name: str
    stat_value: float


@dataclass(frozen=True, slots=True)
class GlobalContextRecord:
    """全局上下文读取结果"""

    novel_title: str
    core_characters: str
    world_setting: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class PivotBlock:
    """诊断转折点分块"""

    chunk_id: int
    text: str
    event_type: str


@dataclass(frozen=True, slots=True)
class HighTensionChunk:
    """高张力段落（2026-08-14 M8a：事实源切换为段落曲线）"""

    paragraph_id: int
    text: str
    tension: float


@dataclass(frozen=True, slots=True)
class RelationChangeRow:
    """关系变更诊断行"""

    chunk_id: int
    from_char: str
    to_char: str
    relation_type: str
    change_type: str


@dataclass(frozen=True, slots=True)
class ForeshadowingChunk:
    """伏笔诊断分块"""

    chunk_id: int
    text: str
    foreshadowing_type: str
    foreshadowing_desc: str


@dataclass(frozen=True, slots=True)
class PivotMoment:
    """高潮时刻分块"""

    chunk_id: int
    text: str
