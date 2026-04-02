"""基于规则的候选名分类器。

设计决策：
1. 精确匹配受保护名单 → 标记为 protected（默认不合并但仍送消歧）
2. 噪音过滤（≤1次+无上下文）→ 唯一的硬丢弃规则
3. 不做外貌描述名匹配 — "灰衣人""白衣少女"在小说中经常是真正有身份揭示的角色，
   正则无法区分，交给 LLM 自己判断
4. 不做后缀匹配 — "赵军"、"张卫"是正常人名，不能因为结尾字就标 protected
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.config import settings

Category = Literal["blacklist", "protected", "normal"]


@dataclass(frozen=True)
class CandidateClassification:
    """候选名分类结果。"""

    name: str
    category: Category
    reason: str  # 分类原因，用于审计日志


def _load_protected_list() -> frozenset[str]:
    """从配置文件加载受保护名单（默认不合并但仍送消歧）。"""
    protected_path = settings.paths.lexicons_dir / "disambig_protected.txt"
    if not protected_path.exists():
        return _DEFAULT_PROTECTED

    names: set[str] = set()
    for line in protected_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            names.add(stripped)
    return frozenset(names) if names else _DEFAULT_PROTECTED


_DEFAULT_PROTECTED: frozenset[str] = frozenset(
    {
        # 泛指代词 — 几乎不可能是真实人物
        "来人",
        "有人",
        "某人",
        "众人",
        "旁人",
        # 通用职位/身份 — 可能是前期未揭示真名的角色，保留送消歧
        "传令兵",
        "侍卫",
        "护卫",
        "手下",
        "家丁",
        "丫鬟",
        "小厮",
    }
)


class CandidateFilter:
    """基于规则的候选名分类器。

    分类规则（按优先级）：
    - blacklist: 出现次数 ≤ 1 且无上下文例句 → 丢弃（可能是噪音）
    - protected: 精确匹配受保护名单 → 送消歧，但 prompt 中标记为"默认不合并"
    - normal: 以上均不匹配 → 正常处理
    """

    def __init__(self) -> None:
        self._protected = _load_protected_list()

    @property
    def protected(self) -> frozenset[str]:
        return self._protected

    def classify(
        self,
        name: str,
        count: int,
        has_context: bool = False,
    ) -> CandidateClassification:
        """对单个候选名进行分类。"""
        # 1. 噪音过滤：唯一硬丢弃规则
        if count <= 1 and not has_context:
            return CandidateClassification(
                name=name,
                category="blacklist",
                reason="出现次数≤1且无上下文例句（噪音过滤）",
            )

        # 2. 精确匹配受保护名单 → 送消歧但默认不合并
        if name in self._protected:
            return CandidateClassification(
                name=name,
                category="protected",
                reason="精确匹配受保护名单",
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

        filtered: blacklist 候选（被丢弃）
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
