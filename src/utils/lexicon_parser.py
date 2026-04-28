from __future__ import annotations

from pathlib import Path


def parse_lexicon_term(line: str) -> str:
    """
    从纯文本或加权词表行解析词条。

    说明: 统一处理空行、注释行和 "词条\t权重" 格式，供 lexicons 与 metrics 共用。
    """
    cleaned = line.strip()
    if not cleaned or cleaned.startswith("#"):
        return ""
    return cleaned.split("\t", 1)[0].strip()


def load_lexicon_terms(path: Path) -> list[str]:
    """
    加载词表文件中的去重词条。

    说明: 抽出纯文本词表加载逻辑，避免 registry 与 loader 各自维护解析细节。
    """
    items: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        term = parse_lexicon_term(line)
        if term and term not in seen:
            seen.add(term)
            items.append(term)
    return items


def load_weighted_lexicon(filepath: str | Path, default_weight: int = 1) -> dict[str, int]:
    """
    加载带权重的词典。

    说明: 将 weighted lexicon parser 从 metrics 下沉到公共层，切断 lexicons -> metrics 的反向依赖。

    参数:
        filepath: 词典文件路径。
        default_weight: 词条没有权重列或权重非法时使用的默认权重。

    返回:
        {词条: 权重} 字典。
    """
    result: dict[str, int] = {}
    path = Path(filepath)

    if not path.exists():
        return result

    for line in path.read_text(encoding="utf-8").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue

        parts = cleaned.split("\t")
        term = parts[0].strip()
        if not term:
            continue

        if len(parts) < 2:
            result[term] = default_weight
            continue

        try:
            weight = int(parts[1].strip())
        except ValueError:
            result[term] = default_weight
            continue

        result[term] = weight

    return result
