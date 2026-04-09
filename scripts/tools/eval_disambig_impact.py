"""词表上下文消歧影响评估脚本"""
from __future__ import annotations

import re
from pathlib import Path

import yaml


def load_conflict_terms(conflict_matrix_path: Path) -> dict:
    with open(conflict_matrix_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    conflict_terms = {}
    for entry in data.get("conflicts", []):
        term = entry["term"]
        conflict_terms[term] = {
            "primary": entry["primary"],
            "referenced_by": entry.get("referenced_by", []),
        }
    return conflict_terms


def count_term_occurrences(text: str, terms: list[str]) -> dict[str, int]:
    counts = {}
    for term in terms:
        count = len(re.findall(re.escape(term), text))
        if count > 0:
            counts[term] = count
    return counts


def evaluate_novel(novel_path: Path, conflict_terms: dict) -> dict:
    encodings = ["utf-8", "gbk", "gb2312"]
    content = None

    for encoding in encodings:
        try:
            with open(novel_path, encoding=encoding) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue

    if content is None:
        return {"error": f"Cannot read {novel_path}"}

    term_counts = count_term_occurrences(content, list(conflict_terms.keys()))

    total_occurrences = sum(term_counts.values())
    duplicate_count = sum(
        count * len(conflict_terms[term]["referenced_by"])
        for term, count in term_counts.items()
    )

    return {
        "novel": novel_path.name,
        "text_length": len(content),
        "conflict_term_counts": term_counts,
        "total_conflict_occurrences": total_occurrences,
        "duplicate_count": duplicate_count,
        "over_count_ratio": duplicate_count / max(total_occurrences, 1),
    }


def main():
    novel_dir = Path("data/novel")
    conflict_matrix_path = Path("data/lexicons/conflict_matrix.yaml")

    print("=" * 60)
    print("词表上下文消歧影响评估")
    print("=" * 60)

    conflict_terms = load_conflict_terms(conflict_matrix_path)
    print(f"\n冲突词条数: {len(conflict_terms)}")

    novel_files = list(novel_dir.glob("*.txt"))
    print(f"小说文件数: {len(novel_files)}")

    total_occurrences = 0
    total_duplicates = 0
    term_totals: dict[str, int] = {}

    for novel_file in novel_files:
        result = evaluate_novel(novel_file, conflict_terms)
        if "error" in result:
            print(f"\n跳过: {result['error']}")
            continue

        print(f"\n小说: {result['novel']}")
        print(f"  文本长度: {result['text_length']:,} 字")
        print(f"  冲突词条出现: {result['total_conflict_occurrences']} 次")
        print(f"  重复计数: {result['duplicate_count']} 次")
        print(f"  重复率: {result['over_count_ratio']:.2%}")

        total_occurrences += result["total_conflict_occurrences"]
        total_duplicates += result["duplicate_count"]

        for term, count in result["conflict_term_counts"].items():
            term_totals[term] = term_totals.get(term, 0) + count

    print("\n" + "=" * 60)
    print("汇总统计")
    print("=" * 60)
    print(f"总冲突词条出现: {total_occurrences} 次")
    print(f"总重复计数: {total_duplicates} 次")
    if total_occurrences > 0:
        print(f"整体重复率: {total_duplicates / total_occurrences:.2%}")

    print("\n高频冲突词条 Top 10:")
    for term, count in sorted(term_totals.items(), key=lambda x: -x[1])[:10]:
        info = conflict_terms[term]
        ref_count = len(info["referenced_by"])
        print(f"  {term}: {count} 次 (被 {ref_count} 个词表引用)")


if __name__ == "__main__":
    main()
