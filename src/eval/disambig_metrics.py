"""
消歧评测指标计算

创建时间: 2026-04-01
创建者: CodeBuddy
任务: P0 评测基线系统

提供金标对比和指标计算功能，支持 A/B 对比。

修改时间: 2026-04-02
修改者: TraeAI
任务: P2.2-entity-type-metrics
修改内容: 新增 compute_metrics_by_entity_type 函数，支持按实体类型分组统计
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class MergeRecord:
    """单条合并决策记录。"""

    alias: str
    system_canonical: str  # 系统判决的规范名
    gold_canonical: str | None = None  # 金标中的规范名
    gold_judgment: str | None = None  # should_merge / should_not_merge / ambiguous
    gold_evidence: str = ""

    @property
    def is_merge(self) -> bool:
        """系统是否执行了合并（alias != system_canonical）。"""
        return self.alias != self.system_canonical

    @property
    def is_correct(self) -> bool | None:
        """与金标对比是否正确。None 表示无法判断。"""
        if self.gold_judgment == "ambiguous":
            return None
        if self.gold_judgment == "should_merge":
            return self.is_merge
        if self.gold_judgment == "should_not_merge":
            return not self.is_merge
        return None


@dataclass
class RunMetrics:
    """单个 run 的评测指标。"""

    run_id: str
    total_merges: int = 0  # 系统执行的合并总数
    correct_merges: int = 0  # 与金标一致的合并数
    wrong_merges: int = 0  # 与金标矛盾的合并数
    ambiguous_merges: int = 0  # 金标无法判断的合并数
    gold_should_merge_total: int = 0  # 金标标记应合并的总数
    missed_merges: int = 0  # 金标标记应合并但系统未合并数
    total_independent: int = 0  # 系统保持独立的名字数
    correct_independent: int = 0  # 与金标一致的独立判断数
    wrong_independent: int = 0  # 与金标矛盾的独立判断数（误合并的来源）

    @property
    def merge_accuracy(self) -> float:
        if self.total_merges == 0:
            return 1.0
        judged = self.total_merges - self.ambiguous_merges
        if judged == 0:
            return float("nan")
        return self.correct_merges / judged

    @property
    def false_merge_rate(self) -> float:
        if self.total_merges == 0:
            return 0.0
        judged = self.total_merges - self.ambiguous_merges
        if judged == 0:
            return float("nan")
        return self.wrong_merges / judged

    @property
    def missed_merge_rate(self) -> float:
        if self.gold_should_merge_total == 0:
            return 0.0
        return self.missed_merges / self.gold_should_merge_total

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total_merges": self.total_merges,
            "correct_merges": self.correct_merges,
            "wrong_merges": self.wrong_merges,
            "ambiguous_merges": self.ambiguous_merges,
            "merge_accuracy": round(self.merge_accuracy, 4)
            if not (self.merge_accuracy != self.merge_accuracy)
            else None,
            "false_merge_rate": round(self.false_merge_rate, 4)
            if not (self.false_merge_rate != self.false_merge_rate)
            else None,
            "gold_should_merge_total": self.gold_should_merge_total,
            "missed_merges": self.missed_merges,
            "missed_merge_rate": round(self.missed_merge_rate, 4),
            "total_independent": self.total_independent,
            "correct_independent": self.correct_independent,
            "wrong_independent": self.wrong_independent,
        }


@dataclass
class BaselineReport:
    """评测基线报告。"""

    generated_at: str = ""
    branch: str = ""
    commit: str = ""
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    aggregate: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "baseline_branch": self.branch,
            "baseline_commit": self.commit,
            "runs": self.runs,
            "aggregate": self.aggregate,
        }


def load_gold_standard(gold_path: Path) -> list[dict]:
    """
    加载金标 JSONL 文件，跳过注释行。

    每行格式:
    {"alias": "伯安", "canonical": "贺重明", "judgment": "should_merge", ...}
    """
    records: list[dict] = []
    with open(gold_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                record = json.loads(line)
                if record.get("judgment"):
                    records.append(record)
            except json.JSONDecodeError:
                continue
    return records


def load_system_merges(
    state: dict | None,
    graph_aliases: list[dict],
) -> list[dict]:
    """
    从系统数据中提取所有合并决策。

    合并决策来源:
    1. disambig_checkpoint 中的 alias_merges
    2. graph_entity_aliases 中的非 primary 记录
    """
    merges: dict[tuple[str, str], dict] = {}

    if state:
        for merge in state.get("alias_merges", []):
            if not isinstance(merge, list | tuple) or len(merge) != 2:
                continue
            alias, canonical = str(merge[0]), str(merge[1])
            if alias == canonical:
                continue
            merges[(alias, canonical)] = {
                "alias": alias,
                "canonical": canonical,
                "source": "checkpoint",
            }

    for ga in graph_aliases:
        alias = ga.get("alias", "")
        canonical = ga.get("canonical", "")
        if alias == canonical or ga.get("is_primary"):
            continue
        key = (alias, canonical)
        if key not in merges:
            merges[key] = {
                "alias": alias,
                "canonical": canonical,
                "source": "graph",
            }

    return list(merges.values())


def compute_run_metrics(
    gold_records: list[dict],
    system_merges: list[dict],
    run_id: str,
) -> tuple[RunMetrics, list[dict]]:
    """
    计算单个 run 的评测指标。

    Args:
        gold_records: 金标记录列表
        system_merges: 系统合并决策列表
        run_id: 运行 ID

    Returns:
        (RunMetrics, details) — 指标和逐条对比明细
    """
    # 构建系统合并查找表（双向：alias=canonical 等价）
    sys_merge_set = {(m["alias"], m["canonical"]) for m in system_merges}
    # 构建等价类查找：给定任一名字，找到其所在合并组的所有名字
    _equiv_groups: list[set[str]] = []
    for m in system_merges:
        a, c = m["alias"], m["canonical"]
        merged = False
        for g in _equiv_groups:
            if a in g or c in g:
                g.add(a)
                g.add(c)
                merged = True
                break
        if not merged:
            _equiv_groups.append({a, c})

    # 构建金标查找表
    gold_merge_set: set[tuple[str, str]] = set()
    gold_independent_set: set[str] = set()
    for rec in gold_records:
        alias = rec["alias"]
        canonical = rec.get("canonical", "")
        judgment = rec.get("judgment", "")
        if judgment == "should_merge" and canonical and alias != canonical:
            gold_merge_set.add((alias, canonical))
        elif judgment == "should_not_merge":
            gold_independent_set.add(alias)

    def _find_canonical(name: str) -> str | None:
        """在系统合并中查找 name 的 canonical。"""
        for a, c in sys_merge_set:
            if a == name:
                return c
        return None

    def _in_same_merge_group(name_a: str, name_b: str) -> bool:
        """检查两个名字是否在同一个合并组中。"""
        for g in _equiv_groups:
            if name_a in g and name_b in g:
                return True
        return False

    metrics = RunMetrics(run_id=run_id)
    details: list[dict] = []

    # 遍历金标记录
    for rec in gold_records:
        alias = rec["alias"]
        canonical = rec.get("canonical", "")
        judgment = rec.get("judgment", "")
        evidence = rec.get("evidence", "")

        if judgment == "should_merge":
            metrics.gold_should_merge_total += 1
            # 系统是否把 alias 和 canonical 合并到了同一组
            if (alias, canonical) in sys_merge_set or (canonical, alias) in sys_merge_set:
                metrics.correct_merges += 1
                details.append(
                    {"alias": alias, "canonical": canonical, "result": "correct_merge", "evidence": evidence}
                )
            elif _in_same_merge_group(alias, canonical):
                metrics.correct_merges += 1
                details.append(
                    {"alias": alias, "canonical": canonical, "result": "correct_merge", "evidence": evidence}
                )
            else:
                # 金标说应该合并，但系统没做
                sys_canonical = _find_canonical(alias)
                if sys_canonical:
                    details.append(
                        {
                            "alias": alias,
                            "canonical": canonical,
                            "system_merged_to": sys_canonical,
                            "result": "wrong_merge_target",
                            "evidence": evidence,
                        }
                    )
                    metrics.wrong_merges += 1
                else:
                    metrics.missed_merges += 1
                    details.append(
                        {"alias": alias, "canonical": canonical, "result": "missed_merge", "evidence": evidence}
                    )

        elif judgment == "should_not_merge":
            if (alias, canonical) in sys_merge_set:
                metrics.wrong_merges += 1
                details.append({"alias": alias, "canonical": canonical, "result": "false_merge", "evidence": evidence})
            else:
                metrics.correct_independent += 1
                details.append(
                    {"alias": alias, "canonical": canonical, "result": "correct_independent", "evidence": evidence}
                )

        elif judgment == "ambiguous":
            metrics.ambiguous_merges += 1
            details.append({"alias": alias, "canonical": canonical, "result": "ambiguous", "evidence": evidence})

    # 系统总合并数（包含金标未覆盖的）
    metrics.total_merges = len(sys_merge_set)

    return metrics, details


def build_aggregate_metrics(run_metrics_list: list[RunMetrics]) -> dict[str, float]:
    """汇总多个 run 的指标。"""
    if not run_metrics_list:
        return {}
    total_merges = sum(rm.total_merges for rm in run_metrics_list)
    correct = sum(rm.correct_merges for rm in run_metrics_list)
    wrong = sum(rm.wrong_merges for rm in run_metrics_list)
    missed = sum(rm.missed_merges for rm in run_metrics_list)
    gold_total = sum(rm.gold_should_merge_total for rm in run_metrics_list)
    judged = total_merges - sum(rm.ambiguous_merges for rm in run_metrics_list)
    return {
        "merge_accuracy": round(correct / judged, 4) if judged else float("nan"),
        "false_merge_rate": round(wrong / judged, 4) if judged else float("nan"),
        "missed_merge_rate": round(missed / gold_total, 4) if gold_total else 0.0,
        "total_merges": total_merges,
        "total_correct": correct,
        "total_wrong": wrong,
        "total_missed": missed,
    }


def format_report_markdown(report: BaselineReport) -> str:
    """将报告格式化为 Markdown。"""
    lines = [
        "# 消歧评测基线报告",
        "",
        f"- 生成时间: {report.generated_at}",
        f"- 分支: `{report.branch}`",
        f"- 提交: `{report.commit}`",
        "",
        "## 各 Run 指标",
        "",
        "| Run ID | 总合并 | 正确 | 错误 | 合并准确率 | 误合并率 | 金标应合并 | 漏合并 | 漏合并率 |",
        "|--------|--------|------|------|-----------|----------|-----------|--------|----------|",
    ]
    for run_id, rm in report.runs.items():
        acc = f"{rm['merge_accuracy']:.2%}" if rm.get("merge_accuracy") is not None else "N/A"
        fmr = f"{rm['false_merge_rate']:.2%}" if rm.get("false_merge_rate") is not None else "N/A"
        mmr = f"{rm['missed_merge_rate']:.2%}" if rm.get("missed_merge_rate") is not None else "N/A"
        lines.append(
            f"| {run_id} | {rm['total_merges']} | {rm['correct_merges']} | {rm['wrong_merges']} "
            f"| {acc} | {fmr} | {rm['gold_should_merge_total']} | {rm['missed_merges']} | {mmr} |"
        )

    agg = report.aggregate
    acc = (
        f"{agg['merge_accuracy']:.2%}"
        if agg.get("merge_accuracy") and agg["merge_accuracy"] == agg["merge_accuracy"]
        else "N/A"
    )
    fmr = (
        f"{agg['false_merge_rate']:.2%}"
        if agg.get("false_merge_rate") and agg["false_merge_rate"] == agg["false_merge_rate"]
        else "N/A"
    )
    mmr_val = agg.get("missed_merge_rate")
    mmr = f"{mmr_val:.2%}" if mmr_val is not None and mmr_val == mmr_val else "N/A"
    lines.extend(
        [
            "",
            "## 汇总",
            "",
            "| 合并准确率 | 误合并率 | 漏合并率 |",
            "|-----------|----------|----------|",
            f"| {acc} | {fmr} | {mmr} |",
        ]
    )
    return "\n".join(lines)


def compare_reports(baseline: BaselineReport, current: BaselineReport) -> str:
    """对比两份报告，输出差异摘要。"""
    lines = [
        "# 基线对比报告",
        "",
        f"- 基线: `{baseline.branch}` @ `{baseline.commit}`",
        f"- 当前: `{current.branch}` @ `{current.commit}`",
        "",
        "| Run ID | 指标 | 基线 | 当前 | 变化 |",
        "|--------|------|------|------|------|",
    ]
    for run_id in baseline.runs:
        b = baseline.runs.get(run_id, {})
        c = current.runs.get(run_id, {})
        for metric_key, metric_label in [
            ("merge_accuracy", "合并准确率"),
            ("false_merge_rate", "误合并率"),
            ("missed_merge_rate", "漏合并率"),
        ]:
            bv = b.get(metric_key)
            cv = c.get(metric_key)
            if bv is None or cv is None or (bv != bv) or (cv != cv):
                continue
            diff = cv - bv
            arrow = "+" if diff > 0 else ""
            lines.append(f"| {run_id} | {metric_label} | {bv:.4f} | {cv:.4f} | {arrow}{diff:.4f} |")

    return "\n".join(lines)


def compute_metrics_by_entity_type(
    gold_records: list[dict],
    system_merges: list[dict],
    run_id: str,
    session: Session,
) -> dict[str, RunMetrics]:
    """
    按实体类型分组统计误合并率。

    数据来源：从 graph_entities JOIN graph_entity_aliases 获取每个 alias 的 entity_type，
    不修改金标格式。

    创建时间: 2026-04-02
    创建者: TraeAI
    任务: P2.2-entity-type-metrics
    """
    from loguru import logger

    from src.storage.repositories import GraphRepository

    graph_repo = GraphRepository(session)
    entities = graph_repo.fetch_entities(run_id)
    alias_map_rows = graph_repo.fetch_alias_map(run_id)

    # 构建 name -> entity_type 查找表
    name_to_type: dict[str, str] = {}
    for e in entities:
        name_to_type[e.canonical_name] = e.entity_type
    for alias, canonical in alias_map_rows.items():
        name_to_type[alias] = name_to_type.get(canonical, "character")

    # 检查覆盖率
    gold_aliases = {r["alias"] for r in gold_records}
    missing_types = gold_aliases - set(name_to_type.keys())
    if missing_types:
        logger.warning(f"entity_type lookup missing for {len(missing_types)} names: {list(missing_types)[:5]}...")

    # 按 entity_type 分组
    type_records: dict[str, list[dict]] = {}
    for record in gold_records:
        alias = record["alias"]
        entity_type = name_to_type.get(alias, "character")
        type_records.setdefault(entity_type, []).append(record)

    # 分别计算各类型指标
    result: dict[str, RunMetrics] = {}
    for entity_type, records in type_records.items():
        metrics, _ = compute_run_metrics(records, system_merges, run_id)
        result[entity_type] = metrics

    return result
