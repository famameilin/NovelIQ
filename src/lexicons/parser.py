from __future__ import annotations

import re
from pathlib import Path

from src.lexicons.constants import SEMANTIC_CATEGORY_MAPPING

# 语义类别词表的分节标记："# ===== 3. 战斗 =====" 形态
_SEMANTIC_SECTION_RE = re.compile(r"#\s*={5,}\s*(\d+)\.\s*(.+?)\s*={5,}")

# 行内注释分隔：词条后跟空白 + # 视为注释（draft 词表 "词  # 证据" 格式）；
# 要求 # 前有空白，避免误伤含 # 的词条本身。
_INLINE_COMMENT_RE = re.compile(r"\s+#")


def _strip_inline_comment(cleaned: str) -> str:
    """剥离行内 '# 注释'，返回词条部分（含可能的 \\t 权重列）"""
    return _INLINE_COMMENT_RE.split(cleaned, maxsplit=1)[0].strip()


def parse_lexicon_term(line: str) -> str:
    """
    从纯文本或加权词表行解析词条

    说明: 统一处理空行、整行/行内注释和 "词条	权重" 格式，供 lexicons 与 metrics 共用
    """
    cleaned = line.strip()
    if not cleaned or cleaned.startswith("#"):
        return ""
    return _strip_inline_comment(cleaned).split("\t", 1)[0].strip()


def load_lexicon_terms(path: Path) -> list[str]:
    """
    加载词表文件中的去重词条

    说明: 抽出纯文本词表加载逻辑，避免 registry 与 loader 各自维护解析细节
    """
    items: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        term = parse_lexicon_term(line)
        if term and term not in seen:
            seen.add(term)
            items.append(term)
    return items


def parse_semantic_category_lexicon(file_path: str) -> dict[str, list[str]]:
    """解析语义类别词表：分节标题给类别、标题后每行一个词条

    说明: 与加权词表解析同族，从 metrics 下沉到公共层，切断 lexicons -> metrics 的
    反向依赖；类别名经 config.constants 的映射表翻译成内部 key。
    """
    categories: dict[str, list[str]] = {}
    current_category: str | None = None
    current_terms: list[str] = []

    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            match = _SEMANTIC_SECTION_RE.match(line)
            if match:
                if current_category and current_terms:
                    categories[current_category] = current_terms
                current_category = SEMANTIC_CATEGORY_MAPPING.get(match.group(2).strip())
                current_terms = []
            elif not line.startswith("#") and current_category:
                current_terms.append(line)

    if current_category and current_terms:
        categories[current_category] = current_terms

    return categories
