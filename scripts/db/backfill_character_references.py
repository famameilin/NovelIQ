"""
角色引用分层重构一次性回填脚本。

默认 dry-run，仅打印影响范围；显式传入 --apply 才会写库。
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.local.character_reference_policy import (
    REFERENCE_CONTRACT_VERSION,
    filter_global_character_names,
    is_global_character_surface_name,
    is_reference_surface_name,
    resolve_global_character_name,
)
from src.storage.db import get_session, init_db
from src.storage.models import (
    AnalysisRun,
    CloudAnalysis,
)
from src.storage.models.core import DisambigCheckpoint
from src.storage.repositories.annotation.characters import apply_reference_resolutions_to_history
from src.storage.repositories import GraphRepository
from src.workflows.annotate_helpers.graph_projection import project_graph_tables

OUTDATED_REFERENCE_CONTRACT_VERSION = 0


@dataclass
class RunBackfillReport:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: dry-run 与 apply 需要输出同一份结构化统计，便于核对污染样本修复范围。
    """

    run_id: str
    character_rows: int = 0
    dialogue_rows: int = 0
    relation_rows: int = 0
    checkpoint_updated: bool = False
    diagnosis_marked_outdated: int = 0
    graph_rebuilt: bool = False
    notes: list[str] = field(default_factory=list)


def _iter_run_ids(session: Session, requested_run_ids: list[str] | None) -> list[str]:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 支持按指定 run 回填，也支持全库 run 批量 dry-run/apply。
    """
    if requested_run_ids:
        return requested_run_ids
    rows = session.execute(select(AnalysisRun.run_id).order_by(AnalysisRun.created_at)).fetchall()
    return [str(row.run_id) for row in rows]


def _coerce_pairs(raw_value: Any) -> list[tuple[str, str]]:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: checkpoint 历史 JSON 中 tuple/list 混用，回填前统一成可校验 pair。
    """
    pairs: list[tuple[str, str]] = []
    if not isinstance(raw_value, list | tuple):
        return pairs
    for item in raw_value:
        if isinstance(item, list | tuple) and len(item) == 2:
            alias, canonical = item
            if isinstance(alias, str) and isinstance(canonical, str):
                pairs.append((alias, canonical))
    return pairs


def _coerce_entity_types(raw_value: Any) -> dict[str, str]:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: entity_types 旧状态可能是 dict 或 pair list，统一后才能过滤引用 surface。
    """
    if isinstance(raw_value, dict):
        return {str(key): str(value) for key, value in raw_value.items() if isinstance(key, str)}
    result: dict[str, str] = {}
    for key, value in _coerce_pairs(raw_value):
        result[key] = value
    return result


def _rewrite_review_status(
    raw_review_status: Any,
    known_canonical_names: set[str],
    reference_resolutions: dict[str, str],
    unresolved_references: set[str],
) -> list[dict[str, Any]]:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: checkpoint 复审状态里的代词 proposed_canonical 也必须降级到引用层语义。
    """
    if not isinstance(raw_review_status, list | tuple):
        return []

    rewritten: list[dict[str, Any]] = []
    for item in raw_review_status:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        state = item.get("state")
        if not isinstance(state, dict):
            continue
        name = str(item["name"])
        next_state = dict(state)
        proposed = next_state.get("proposed_canonical")

        if is_reference_surface_name(name):
            resolved = reference_resolutions.get(name)
            if resolved:
                next_state["status"] = "resolved"
                next_state["proposed_canonical"] = resolved
            else:
                unresolved_references.add(name)
                next_state["status"] = "unresolved"
                next_state["proposed_canonical"] = None
            rewritten.append({"name": name, "state": next_state})
            continue

        if isinstance(proposed, str) and proposed != name:
            resolved_proposed = resolve_global_character_name(proposed)
            if resolved_proposed is None:
                next_state["proposed_canonical"] = None
                next_state["status"] = "review"
            else:
                known_canonical_names.add(resolved_proposed)
                next_state["proposed_canonical"] = resolved_proposed
        rewritten.append({"name": name, "state": next_state})

    return rewritten


def _rewrite_checkpoint_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 将旧 checkpoint 中的代词 canonical/alias 拆到 unresolved_references/reference_resolutions。
    """
    discovered_names = {
        str(name).strip()
        for name in payload.get("discovered_names", []) or []
        if isinstance(name, str) and str(name).strip()
    }
    known_canonical_names = set(filter_global_character_names(payload.get("known_canonical_names", []) or []))
    unresolved_references = {
        str(name).strip()
        for name in payload.get("unresolved_references", []) or []
        if isinstance(name, str) and is_reference_surface_name(name)
    }
    reference_resolutions = {
        reference: canonical
        for reference, canonical in _coerce_pairs(payload.get("reference_resolutions", []))
        if is_reference_surface_name(reference) and is_global_character_surface_name(canonical)
    }

    for name in discovered_names:
        if is_reference_surface_name(name):
            unresolved_references.add(name)

    alias_merges: list[tuple[str, str]] = []
    seen_aliases: set[str] = set()
    for alias, canonical in _coerce_pairs(payload.get("alias_merges", [])):
        resolved_canonical = resolve_global_character_name(canonical)
        if is_reference_surface_name(alias):
            if resolved_canonical is not None:
                reference_resolutions[alias] = resolved_canonical
                known_canonical_names.add(resolved_canonical)
                unresolved_references.discard(alias)
            else:
                unresolved_references.add(alias)
            continue
        if resolved_canonical is None or alias == resolved_canonical or alias in seen_aliases:
            continue
        alias_merges.append((alias, resolved_canonical))
        seen_aliases.add(alias)
        known_canonical_names.add(resolved_canonical)

    unresolved_references.difference_update(reference_resolutions.keys())
    entity_types = {
        name: entity_type
        for name, entity_type in _coerce_entity_types(payload.get("entity_types", {})).items()
        if is_global_character_surface_name(name)
    }
    review_status = _rewrite_review_status(
        payload.get("review_status", []),
        known_canonical_names,
        reference_resolutions,
        unresolved_references,
    )

    rewritten = dict(payload)
    rewritten["version"] = 3
    rewritten["known_canonical_names"] = sorted(filter_global_character_names(known_canonical_names))
    rewritten["alias_merges"] = alias_merges
    rewritten["unresolved_references"] = sorted(unresolved_references)
    rewritten["reference_resolutions"] = sorted(reference_resolutions.items())
    rewritten["review_status"] = review_status
    rewritten["entity_types"] = entity_types

    return rewritten, rewritten != payload


def _extract_checkpoint_reference_resolutions(
    session: Session,
    run_id: str,
    *,
    apply: bool,
) -> tuple[dict[str, str], bool]:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 历史回填必须先读 checkpoint/reference_resolutions，再驱动 chunk_* resolved 字段回写。
    """
    checkpoint = session.execute(
        select(DisambigCheckpoint).where(DisambigCheckpoint.run_id == run_id)
    ).scalar_one_or_none()
    if checkpoint is None or not checkpoint.state_json:
        return {}, False
    payload = json.loads(checkpoint.state_json)
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid disambig checkpoint for run_id={run_id}: expected dict")
    rewritten, changed = _rewrite_checkpoint_payload(payload)
    if changed and apply:
        checkpoint.state_json = json.dumps(rewritten, ensure_ascii=False)
    reference_resolutions = {
        reference: canonical
        for reference, canonical in _coerce_pairs(rewritten.get("reference_resolutions", []))
        if is_reference_surface_name(reference) and is_global_character_surface_name(canonical)
    }
    return reference_resolutions, changed


def _json_contains_reference_names(raw_json: str | None) -> bool:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 标记 diagnosis 过期前需要检测角色字段是否仍包含未解析代词/泛称。
    """
    if not raw_json:
        return False
    try:
        value = json.loads(raw_json)
    except json.JSONDecodeError:
        return False
    names: Iterable[Any]
    if isinstance(value, dict):
        names = value.keys()
    elif isinstance(value, list):
        names = value
    else:
        return False
    return any(isinstance(name, str) and is_reference_surface_name(name) for name in names)


def _mark_polluted_diagnosis(session: Session, run_id: str, *, apply: bool) -> int:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 受旧 reference 合同污染的 diagnosis 必须显式过期，由用户重跑云端诊断。
    """
    rows = session.execute(select(CloudAnalysis).where(CloudAnalysis.run_id == run_id)).scalars().all()
    marked = 0
    for row in rows:
        polluted = row.reference_contract_version != REFERENCE_CONTRACT_VERSION or any(
            _json_contains_reference_names(raw_value)
            for raw_value in (row.arc_scores, row.focus_characters, row.main_characters, row.core_cast)
        )
        if not polluted:
            continue
        marked += 1
        if apply:
            row.reference_contract_version = OUTDATED_REFERENCE_CONTRACT_VERSION
    return marked


def backfill_run(session: Session, run_id: str, *, apply: bool, rebuild_graph: bool) -> RunBackfillReport:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 单 run 粒度执行完整 reference 回填，先消费 checkpoint/reference_resolutions，再反写历史行。
    """
    report = RunBackfillReport(run_id=run_id)
    reference_resolutions, checkpoint_updated = _extract_checkpoint_reference_resolutions(
        session,
        run_id,
        apply=apply,
    )
    row_counts = apply_reference_resolutions_to_history(
        session,
        run_id,
        reference_resolutions,
        apply=apply,
    )
    report.character_rows = row_counts["chunk_characters"]
    report.dialogue_rows = row_counts["chunk_dialogues"]
    report.relation_rows = row_counts["chunk_relations"]
    report.checkpoint_updated = checkpoint_updated
    report.diagnosis_marked_outdated = _mark_polluted_diagnosis(session, run_id, apply=apply)

    if apply and rebuild_graph:
        GraphRepository(session).reset_graph_tables(run_id)
        session.flush()
        project_graph_tables(run_id=run_id, session=session, rebuild=True)
        report.graph_rebuilt = True
    elif not apply and rebuild_graph:
        report.notes.append("dry-run: graph rebuild would run with --apply")
    return report


def _parse_args() -> argparse.Namespace:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 提供安全的命令行入口，默认 dry-run，显式 --apply 才写库。
    """
    parser = argparse.ArgumentParser(description="Backfill character reference fields for existing runs.")
    parser.add_argument("--run-id", action="append", dest="run_ids", help="Run id to backfill; repeatable.")
    parser.add_argument("--apply", action="store_true", help="Write changes. Default is dry-run.")
    parser.add_argument(
        "--skip-graph-rebuild",
        action="store_true",
        help="Only with --apply: skip graph reset/rebuild after annotation/checkpoint backfill.",
    )
    return parser.parse_args()


def main() -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 执行一次性数据库回填并输出每个 run 的影响统计。
    """
    args = _parse_args()
    init_db()
    with get_session() as session:
        run_ids = _iter_run_ids(session, args.run_ids)
        reports = [
            backfill_run(
                session,
                run_id,
                apply=bool(args.apply),
                rebuild_graph=not bool(args.skip_graph_rebuild),
            )
            for run_id in run_ids
        ]
        if args.apply:
            session.commit()
        else:
            session.rollback()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] processed {len(reports)} run(s)")
    for report in reports:
        print(
            f"- run_id={report.run_id} characters={report.character_rows} dialogues={report.dialogue_rows} "
            f"relations={report.relation_rows} checkpoint_updated={report.checkpoint_updated} "
            f"diagnosis_outdated={report.diagnosis_marked_outdated} graph_rebuilt={report.graph_rebuilt}"
        )
        for note in report.notes:
            print(f"  note: {note}")


if __name__ == "__main__":
    main()
