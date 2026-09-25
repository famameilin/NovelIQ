"""角色与图谱 tab 组装"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.api.models.graph import GraphSnapshotResponse
from src.api.services.results_queries.characters import _fetch_characters
from src.api.services.results_queries.diagnosis import _fetch_diagnosis, _has_diagnosis_result
from src.api.services.results_queries.graph import _fetch_graph_changes_page, _fetch_graph_snapshot
from src.api.services.results_queries.graph_metrics import compute_graph_metrics
from src.storage.repositories import AnnotationRepository, StatsRepository


def build_character_function_tab(run_id: str, novel_id: str, session: Session) -> dict[str, Any]:
    """功能与焦点 tab：角色列表（含焦点对齐）+ 诊断焦点结构切片"""
    stats_repo = StatsRepository(session)
    annotation_repo = AnnotationRepository(session)

    diagnosis = _fetch_diagnosis(run_id, novel_id, stats_repo)
    arc_scores: dict[str, float] | None = None
    focus_characters: list[str] | None = None
    main_characters: list[str] | None = None
    if diagnosis is not None and _has_diagnosis_result(diagnosis):
        arc_scores = diagnosis.arc_scores
        focus_characters = diagnosis.focus_characters
        main_characters = diagnosis.main_characters

    return {
        "run_id": run_id,
        "characters": _fetch_characters(
            run_id, annotation_repo, arc_scores, focus_characters, main_characters, limit=None
        ),
        "focus_structure": diagnosis.focus_structure if diagnosis is not None else None,
        "focus_characters": focus_characters,
        "arc_scores": arc_scores,
    }


def build_graph_network_tab(run_id: str, session: Session, chapter_id: int | None = None) -> dict[str, Any]:
    """
    图谱 tab：图快照 + 登场次数 + 图算法指标 + 变化总数

    - 快照缺失（无图数据或章节越界）时 snapshot=None 并回显原因，不伪造空图；
    - 登场次数沿用 /characters 的别名归并口径，仅回 name + appearance_count；
    - 变化总数取 page_info.total（limit=1 的首页查询），不回变化明细。
    """
    annotation_repo = AnnotationRepository(session)

    snapshot_reason: str | None = None
    snapshot: GraphSnapshotResponse | None = None
    try:
        payload = _fetch_graph_snapshot(run_id, annotation_repo, chapter_id=chapter_id)
        snapshot = GraphSnapshotResponse.model_validate(payload)
    except (ValueError, LookupError) as exc:
        snapshot_reason = str(exc)

    changes_page = _fetch_graph_changes_page(run_id, annotation_repo, changes_limit=1)
    change_total = int(changes_page.get("page_info", {}).get("total") or 0)

    return {
        "run_id": run_id,
        "snapshot": snapshot,
        "character_appearances": [
            {"name": character.name, "appearance_count": character.appearance_count}
            for character in _fetch_characters(run_id, annotation_repo, limit=None)
        ],
        "graph_metrics": compute_graph_metrics(run_id, session),
        "change_total": change_total,
        "unavailable_reason": snapshot_reason,
    }
