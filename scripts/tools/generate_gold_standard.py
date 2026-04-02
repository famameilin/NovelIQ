"""
从数据库提取消歧决策，生成金标 JSONL 模板供人工审核。

创建时间: 2026-04-01
创建者: CodeBuddy
任务: P0 评测基线系统 — 金标集生成

用法:
    uv run python -m scripts.tools.generate_gold_standard --run-ids 6b401f00,abededd4
    uv run python -m scripts.tools.generate_gold_standard --run-ids 6b401f00 --output custom.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
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

DEFAULT_OUTPUT_DIR = Path(_project_root) / "data" / "gold_standards" / "disambiguation"


def load_disambig_state(session, run_id: str) -> dict | None:
    """从 disambig_checkpoint 加载消歧状态。"""
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


def load_graph_aliases(session, run_id: str) -> list[dict]:
    """从 graph_entity_aliases 获取已落库的别名合并记录。"""
    rows = session.execute(
        sa_text("""
            SELECT
                gea.alias,
                ge.canonical_name,
                gea.confidence,
                gea.source_type,
                gea.evidence,
                gea.is_primary
            FROM graph_entity_aliases gea
            JOIN graph_entities ge ON gea.entity_id = ge.entity_id
            WHERE gea.run_id = :rid
            ORDER BY ge.canonical_name, gea.alias
        """),
        {"rid": run_id},
    ).fetchall()
    return [
        {
            "alias": row[0],
            "canonical": row[1],
            "confidence": float(row[2]) if row[2] is not None else None,
            "source_type": row[3],
            "evidence": row[4],
            "is_primary": row[5],
        }
        for row in rows
    ]


def load_novel_title(session, run_id: str) -> str:
    """获取 run 对应的小说标题。"""
    row = session.execute(
        sa_text("SELECT title FROM analysis_runs WHERE run_id = :rid"),
        {"rid": run_id},
    ).fetchone()
    return row[0] if row and row[0] else "unknown"


def build_gold_records(
    state: dict | None,
    graph_aliases: list[dict],
    run_id: str,
) -> list[dict]:
    """
    合并 disambig_checkpoint 和 graph_entity_aliases 的信息，
    构建待人工审核的金标记录。
    """
    records: dict[tuple[str, str], dict] = {}

    # 1) 从 alias_merges 提取（这是消歧判决的直接产出）
    if state:
        alias_merges = state.get("alias_merges", [])
        review_status = {item["name"]: item["state"] for item in state.get("review_status", [])}
        for merge in alias_merges:
            if not isinstance(merge, (list, tuple)) or len(merge) != 2:
                continue
            alias, canonical = str(merge[0]), str(merge[1])
            if alias == canonical:
                continue
            key = (alias, canonical)
            rs = review_status.get(alias, {})
            records[key] = {
                "alias": alias,
                "canonical": canonical,
                "judgment": "",  # 待人工填写
                "evidence": "",
                "annotator": "",
                "annotated_at": "",
                "_meta": {
                    "source": "disambig_checkpoint",
                    "run_id": run_id,
                    "confidence": rs.get("confidence", ""),
                    "evidence_strength": rs.get("evidence_strength", ""),
                    "status": rs.get("status", ""),
                },
            }

    # 2) 从 graph_entity_aliases 提取（补充落库信息）
    for ga in graph_aliases:
        alias = ga["alias"]
        canonical = ga["canonical"]
        if alias == canonical or ga.get("is_primary"):
            continue
        key = (alias, canonical)
        evidence_text = ga.get("evidence", "") or ""
        if key in records:
            # 补充 graph 层证据
            existing_evidence = records[key].get("evidence", "")
            if evidence_text and evidence_text not in existing_evidence:
                records[key]["_meta"]["graph_source_type"] = ga.get("source_type", "")
                records[key]["_meta"]["graph_confidence"] = ga.get("confidence")
                if not existing_evidence:
                    records[key]["evidence"] = evidence_text
        else:
            records[key] = {
                "alias": alias,
                "canonical": canonical,
                "judgment": "",
                "evidence": evidence_text,
                "annotator": "",
                "annotated_at": "",
                "_meta": {
                    "source": "graph_entity_aliases",
                    "run_id": run_id,
                    "graph_source_type": ga.get("source_type", ""),
                    "graph_confidence": ga.get("confidence"),
                },
            }

    # 3) 从 review_status 中提取已确认的独立名字（自映射 resolved）
    if state:
        review_status = state.get("review_status", [])
        known_canonical = set(state.get("known_canonical_names", []))
        for item in review_status:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            st = item.get("state", {})
            if st.get("status") == "resolved" and name in known_canonical:
                # 这是一个确认独立存在的角色，不需要合并，但仍记录
                # 只在 name != proposed_canonical 时记录为 "should_not_merge"
                canonical = st.get("proposed_canonical", name)
                if canonical and canonical != name:
                    key = (name, canonical)
                    if key not in records:
                        records[key] = {
                            "alias": name,
                            "canonical": canonical,
                            "judgment": "",
                            "evidence": "",
                            "annotator": "",
                            "annotated_at": "",
                            "_meta": {
                                "source": "review_status_resolved",
                                "run_id": run_id,
                                "confidence": st.get("confidence", ""),
                                "evidence_strength": st.get("evidence_strength", ""),
                                "status": "resolved",
                            },
                        }

    return list(records.values())


def resolve_run_ids(session, ids: list[str]) -> dict[str, str]:
    """
    将输入的 task_id（8位）或 run_id（36位）统一解析为 run_id。

    Returns:
        {原始输入: 完整run_id} 映射
    """
    from src.storage.id_mapping import TaskIDNotFoundError, task_id_to_run_id

    resolved: dict[str, str] = {}
    for rid in ids:
        if len(rid) == 36 and "-" in rid:
            resolved[rid] = rid
        else:
            try:
                full = task_id_to_run_id(rid, session)
                resolved[rid] = full
            except TaskIDNotFoundError:
                print(f"  [WARN] 未找到 task_id={rid} 对应的 run_id，跳过")
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser(description="从 DB 提取消歧决策，生成金标 JSONL 模板")
    parser.add_argument(
        "--run-ids",
        required=True,
        help="逗号分隔的 task_id 或 run_id 列表（8位或36位均可）",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"输出目录（默认 {DEFAULT_OUTPUT_DIR}）",
    )
    args = parser.parse_args()

    raw_ids = [rid.strip() for rid in args.run_ids.split(",") if rid.strip()]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"待处理的 ID: {raw_ids}")
    print(f"输出目录: {output_dir}")
    print()

    with get_session() as session:
        id_map = resolve_run_ids(session, raw_ids)
        if not id_map:
            print("错误: 无有效 ID，退出")
            return

        print(f"ID 映射: {json.dumps(id_map, indent=2)}")
        print()

        for label, run_id in id_map.items():
            print(f"--- 处理 run_id: {run_id} (输入: {label}) ---")

            title = load_novel_title(session, run_id)
            state = load_disambig_state(session, run_id)
            graph_aliases = load_graph_aliases(session, run_id)

            if not state and not graph_aliases:
                print(f"  警告: run_id={run_id} 无消歧数据，跳过")
                print()
                continue

            print(f"  小说: {title}")
            print(f"  checkpoint: {'有' if state else '无'}")
            print(f"  graph_aliases: {len(graph_aliases)} 条")
            if state:
                merges = state.get("alias_merges", [])
                review = state.get("review_status", [])
                print(f"  alias_merges: {len(merges)} 条")
                print(f"  review_status: {len(review)} 条")

            records = build_gold_records(state, graph_aliases, run_id)

            output_path = output_dir / f"{run_id}.jsonl"
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"# 金标集模板 — run_id={run_id}, novel={title}\n")
                f.write(f"# 生成时间: {datetime.now(timezone.utc).isoformat()}\n")
                f.write(f"# 请填写 judgment: should_merge / should_not_merge / ambiguous\n")
                f.write(f"# _meta 字段为系统自动生成，请勿修改\n")
                f.write("\n")
                for record in records:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

            print(f"  生成金标记录: {len(records)} 条")
            print(f"  输出文件: {output_path}")
            print()


if __name__ == "__main__":
    main()
