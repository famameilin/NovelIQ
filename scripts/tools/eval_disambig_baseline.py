"""
消歧评测基线 CLI

用法:
    # 生成首份基线报告
    uv run python -m scripts.tools.eval_disambig_baseline --run-ids 6b401f00,abededd4

    # 与已有基线对比
    uv run python -m scripts.tools.eval_disambig_baseline --run-ids 6b401f00 --compare baseline_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _project_root)

from dotenv import load_dotenv

load_dotenv(os.path.join(_project_root, ".env"))

import src.config  # noqa: E402
from src.storage.db import get_session  # noqa: E402
from sqlalchemy import text as sa_text  # noqa: E402

from src.eval.disambig_metrics import (  # noqa: E402
    BaselineReport,
    build_aggregate_metrics,
    compare_reports,
    compute_run_metrics,
    format_report_markdown,
    load_gold_standard,
    load_system_merges,
)
from src.storage.id_mapping import TaskIDNotFoundError, task_id_to_run_id  # noqa: E402

GOLD_DIR = Path(_project_root) / "data" / "gold_standards" / "disambiguation"


def _resolve_run_ids(session, raw_ids: list[str]) -> dict[str, str]:
    """将 task_id（8位）或 run_id（36位）统一解析为 run_id"""
    resolved: dict[str, str] = {}
    for rid in raw_ids:
        if len(rid) == 36 and "-" in rid:
            resolved[rid] = rid
        else:
            try:
                full = task_id_to_run_id(rid, session)
                resolved[rid] = full
            except TaskIDNotFoundError:
                print(f"[WARN] 未找到 task_id={rid} 对应的 run_id，跳过")
    return resolved


def _get_git_info() -> tuple[str, str]:
    """获取当前 git branch 和 commit"""
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, cwd=_project_root,
        ).decode().strip()
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, cwd=_project_root,
        ).decode().strip()
        return branch, commit
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown", "unknown"


def _load_disambig_state(session, run_id: str) -> dict | None:
    row = session.execute(
        sa_text("SELECT state_json FROM disambig_checkpoint WHERE run_id = :rid"),
        {"rid": run_id},
    ).fetchone()
    if not row or not row[0]:
        return None
    raw = str(row[0])
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(json.loads(raw) if raw.startswith('"') else raw)


def _load_graph_aliases(session, run_id: str) -> list[dict]:
    rows = session.execute(
        sa_text("""
            SELECT gea.alias, ge.canonical_name, gea.confidence, gea.source_type, gea.is_primary
            FROM graph_entity_aliases gea
            JOIN graph_entities ge ON gea.entity_id = ge.entity_id
            WHERE gea.run_id = :rid
        """),
        {"rid": run_id},
    ).fetchall()
    return [
        {"alias": row[0], "canonical": row[1], "confidence": float(row[2]) if row[2] else None,
         "source_type": row[3], "is_primary": row[4]}
        for row in rows
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="消歧评测基线系统")
    parser.add_argument("--run-ids", required=True, help="逗号分隔的 run_id 列表")
    parser.add_argument("--compare", default=None, help="与已有基线 JSON 报告对比")
    parser.add_argument("--output", default=None, help="输出 JSON 报告路径（默认 baseline_report.json）")
    args = parser.parse_args()

    raw_ids = [rid.strip() for rid in args.run_ids.split(",") if rid.strip()]
    branch, commit = _get_git_info()

    print(f"消歧评测基线系统")
    print(f"分支: {branch}, 提交: {commit}")
    print(f"Run IDs: {raw_ids}")
    print()

    all_metrics = []
    all_details: dict[str, list[dict]] = {}

    with get_session() as session:
        id_map = _resolve_run_ids(session, raw_ids)
        if not id_map:
            print("错误: 无有效 ID，退出")
            return

        print(f"ID 映射: {json.dumps(id_map, indent=2)}")
        print()

        for run_id in id_map.values():
            gold_path = GOLD_DIR / f"{run_id}.jsonl"
            if not gold_path.exists():
                print(f"[WARN] 金标文件不存在: {gold_path}，跳过")
                continue

            gold_records = load_gold_standard(gold_path)
            state = _load_disambig_state(session, run_id)
            graph_aliases = _load_graph_aliases(session, run_id)
            system_merges = load_system_merges(state, graph_aliases)

            metrics, details = compute_run_metrics(gold_records, system_merges, run_id)
            all_metrics.append(metrics)
            all_details[run_id] = details

            print(f"Run {run_id}:")
            print(f"  系统合并: {metrics.total_merges}, 正确: {metrics.correct_merges}, "
                  f"错误: {metrics.wrong_merges}, 歧义: {metrics.ambiguous_merges}")
            print(f"  合并准确率: {metrics.merge_accuracy:.2%}" if metrics.total_merges else "  合并准确率: N/A")
            print(f"  误合并率: {metrics.false_merge_rate:.2%}" if metrics.total_merges else "  误合并率: N/A")
            print(f"  漏合并: {metrics.missed_merges}/{metrics.gold_should_merge_total}")
            print(f"  金标覆盖: {len(gold_records)} 条")
            print()

    aggregate = build_aggregate_metrics(all_metrics)

    report = BaselineReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        branch=branch,
        commit=commit,
        runs={rm.run_id: rm.to_dict() for rm in all_metrics},
        aggregate=aggregate,
    )

    # 输出 JSON
    output_path = Path(args.output) if args.output else Path("baseline_report.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
    print(f"JSON 报告: {output_path}")

    # 输出 Markdown
    md_path = output_path.with_suffix(".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(format_report_markdown(report))
    print(f"Markdown 报告: {md_path}")

    # 输出详细对比明细
    for run_id, details in all_details.items():
        detail_path = output_path.parent / f"{run_id}_details.json"
        with open(detail_path, "w", encoding="utf-8") as f:
            json.dump(details, f, ensure_ascii=False, indent=2)
        print(f"明细文件: {detail_path}")

    # A/B 对比
    if args.compare:
        compare_path = Path(args.compare)
        if compare_path.exists():
            with open(compare_path, "r", encoding="utf-8") as f:
                baseline_data = json.load(f)
            baseline_report = BaselineReport(
                generated_at=baseline_data.get("generated_at", ""),
                branch=baseline_data.get("baseline_branch", ""),
                commit=baseline_data.get("baseline_commit", ""),
                runs=baseline_data.get("runs", {}),
                aggregate=baseline_data.get("aggregate", {}),
            )
            diff_md = compare_reports(baseline_report, report)
            diff_path = output_path.parent / "baseline_diff.md"
            with open(diff_path, "w", encoding="utf-8") as f:
                f.write(diff_md)
            print(f"对比报告: {diff_path}")
        else:
            print(f"[WARN] 基线报告不存在: {compare_path}")

    print("\n完成。")


if __name__ == "__main__":
    main()
