"""基于规则的候选名分类器。

设计决策：
1. 不做硬过滤（protected 仍送消歧）— 避免"灰衣人=白芷"这种正确合并被拦住
2. 黑名单从配置加载 — data/lexicons/disambig_blacklist.txt，支持按小说定制
3. 分类原因写入审计日志 — 便于后续回溯"为什么这个候选被拦截"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.config import settings

Category = Literal["blacklist", "protected", "normal"]


@dataclass(frozen=True)
class CandidateClassification:
    """候选名分类结果。"""

    name: str
    category: Category
    reason: str  # 分类原因，用于审计日志


# 含以下字结尾的候选，标记为 protected（群体/组织/外貌描述）
PROTECTED_SUFFIXES: tuple[str, ...] = (
    "卫", "军", "队", "营", "团", "帮", "派", "门", "宗", "族",
)

# 纯外貌描述的正则
APPEARANCE_PATTERN: re.Pattern[str] = re.compile(
    r"^(灰衣|黑衣|白衣|青衣|红衣|金甲|银甲)?"
    r"(人|少女|少年|男子|女子|老者|老妪|婴孩|婴儿|青年|壮汉)$"
)


def _load_blacklist() -> frozenset[str]:
    """从配置文件加载黑名单。"""
    blacklist_path = settings.paths.lexicons_dir / "disambig_blacklist.txt"
    if not blacklist_path.exists():
        return _DEFAULT_BLACKLIST

    names: set[str] = set()
    for line in blacklist_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            names.add(stripped)
    return frozenset(names) if names else _DEFAULT_BLACKLIST


_DEFAULT_BLACKLIST: frozenset[str] = frozenset({
    "来人", "有人", "某人", "众人", "旁人",
    "传令兵", "侍卫", "护卫", "手下", "家丁", "丫鬟", "小厮",
})


class CandidateFilter:
    """基于规则的候选名分类器。

    分类规则：
    - blacklist: 精确匹配黑名单 → 丢弃，不送消歧
    - blacklist: 出现次数 ≤ 1 且无上下文例句 → 丢弃（可能是 OCR/分词噪音）
    - protected: 匹配 PROTECTED_SUFFIXES → 送消歧，但 prompt 中标记为"默认不合并"
    - protected: 匹配 APPEARANCE_PATTERN → 送消歧，但 prompt 中标记为"默认不合并"
    - normal: 以上均不匹配 → 正常处理
    """

    def __init__(self) -> None:
        self._blacklist = _load_blacklist()

    @property
    def blacklist(self) -> frozenset[str]:
        return self._blacklist

    def classify(
        self,
        name: str,
        count: int,
        has_context: bool = False,
    ) -> CandidateClassification:
        """对单个候选名进行分类。"""
        # 1. 精确匹配黑名单
        if name in self._blacklist:
            return CandidateClassification(
                name=name,
                category="blacklist",
                reason="精确匹配黑名单",
            )

        # 2. 低频无上下文 → 可能是噪音
        if count <= 1 and not has_context:
            return CandidateClassification(
                name=name,
                category="blacklist",
                reason="出现次数≤1且无上下文例句（可能是噪音）",
            )

        # 3. 群体/组织后缀
        if any(name.endswith(suffix) for suffix in PROTECTED_SUFFIXES):
            return CandidateClassification(
                name=name,
                category="protected",
                reason=f"以群体/组织后缀结尾（{[s for s in PROTECTED_SUFFIXES if name.endswith(s)][0]}）",
            )

        # 4. 外貌描述名
        if APPEARANCE_PATTERN.match(name):
            return CandidateClassification(
                name=name,
                category="protected",
                reason="匹配外貌描述模式",
            )

        return CandidateClassification(
            name=name,
            category="normal",
            reason="普通候选",
        )

    def classify_batch(
        self,
        candidates: list[dict],
        context_sentences: dict[str, str] | None = None,
    ) -> tuple[list[CandidateClassification], list[CandidateClassification]]:
        """批量分类候选名，返回 (filtered, remaining)。

        filtered: blacklist 候选（被过滤）
        remaining: protected + normal 候选（保留送消歧）
        """
        filtered: list[CandidateClassification] = []
        remaining: list[CandidateClassification] = []

        for item in candidates:
            name = str(item["name"])
            count = int(item.get("count", 0))
            has_ctx = bool(context_sentences and context_sentences.get(name, "").strip())
            cls = self.classify(name, count, has_context=has_ctx)

            if cls.category == "blacklist":
                filtered.append(cls)
            else:
                remaining.append(cls)

        return filtered, remaining
