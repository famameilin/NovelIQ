"""基于规则的候选名分类器

设计决策：
1. 精确匹配受保护名单 → 标记为 protected（默认不合并但仍送消歧）
2. 低频且暂无上下文的真实候选 → 标记为 deferred，暂不送模型，但必须保留到后续复审/终消歧
3. 只有明显脏 token 才进入 blacklist，避免把低频正式名直接蒸发
4. 不做外貌描述名匹配、不做后缀匹配，避免用脆弱正则误杀真实角色
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.config import settings
from src.models.local.character_reference_policy import is_reference_surface_name

Category = Literal["blacklist", "protected", "reference", "deferred", "normal"]


@dataclass(frozen=True)
class CandidateClassification:
    """候选名分类结果"""

    name: str
    category: Category
    reason: str  # 分类原因，用于审计日志


def _contains_name_like_char(name: str) -> bool:
    """
    判断候选中是否包含常见的人名字符

    这里只做极保守判断，用来区分“明显脏 token”和“至少像一个名字/称呼”的候选
    """
    for char in name:
        if "\u4e00" <= char <= "\u9fff":
            return True
        if char.isalpha():
            return True
    return False


def _is_obvious_noise_candidate(name: str) -> bool:
    """
    判断候选是否明显属于脏 token

    仅对空串、纯数字、纯符号等明显不可能成为角色名的候选做硬丢弃
    """
    stripped = name.strip()
    if not stripped:
        return True
    if stripped.isdigit():
        return True
    return not _contains_name_like_char(stripped)


def _load_protected_list() -> frozenset[str]:
    """从配置文件加载受保护名单（默认不合并但仍送消歧）"""
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
        "教授",
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
    """基于规则的候选名分类器

    分类规则（按优先级）：
    - blacklist: 明显脏 token（空串/纯数字/纯符号）→ 丢弃
    - reference: 代词/局部引用 → 送消歧，但禁止作为普通 canonical
    - protected: 精确匹配受保护名单 → 送消歧，但 prompt 中标记为"默认不合并"
    - deferred: 出现次数 ≤ 1 且无上下文例句 → 暂不送消歧，但保留到后续复审/终消歧
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
        """
        对单个候选名进行分类

        修改时间: 2026-04-29
        任务: 角色引用分层重构
        修改原因: 将代词/局部引用识别为 reference 类，防止后续作为普通 canonical 候选。
        """
        stripped_name = name.strip()

        # 1. 明显脏 token：唯一硬丢弃规则
        if _is_obvious_noise_candidate(stripped_name):
            return CandidateClassification(
                name=stripped_name,
                category="blacklist",
                reason="明显脏 token（空串/纯数字/纯符号）",
            )

        # 2. 代词/局部引用：保留给消歧解析，但不能进入普通角色主链
        if is_reference_surface_name(stripped_name):
            return CandidateClassification(
                name=stripped_name,
                category="reference",
                reason="角色引用 surface（代词/局部引用，禁止作为普通 canonical）",
            )

        # 3. 精确匹配受保护名单 → 送消歧但默认不合并
        if stripped_name in self._protected:
            return CandidateClassification(
                name=stripped_name,
                category="protected",
                reason="精确匹配受保护名单",
            )

        # 4. 低频且暂无上下文：先保留，延后到后续复审/终消歧
        if count <= 1 and not has_context:
            return CandidateClassification(
                name=stripped_name,
                category="deferred",
                reason="出现次数≤1且暂无可用上下文（延后处理）",
            )

        return CandidateClassification(
            name=stripped_name,
            category="normal",
            reason="普通候选",
        )

    def classify_batch(
        self,
        candidates: list[dict],
        context_sentences: dict[str, str] | None = None,
    ) -> tuple[list[CandidateClassification], list[CandidateClassification], list[CandidateClassification]]:
        """批量分类候选名，返回 (filtered, deferred, remaining)

        修改时间: 2026-04-29
        任务: 角色引用分层重构
        修改原因: reference 类需要随 protected + normal 一起进入模型解析，但不进入 deferred。

        filtered: blacklist 候选（被丢弃）
        deferred: deferred 候选（暂不送模型，但保留）
        remaining: reference + protected + normal 候选（保留送消歧）
        """
        filtered: list[CandidateClassification] = []
        deferred: list[CandidateClassification] = []
        remaining: list[CandidateClassification] = []

        for item in candidates:
            name = str(item["name"])
            count = int(item.get("count", 0))
            has_ctx = bool(context_sentences and context_sentences.get(name, "").strip())
            cls = self.classify(name, count, has_context=has_ctx)

            if cls.category == "blacklist":
                filtered.append(cls)
            elif cls.category == "deferred":
                deferred.append(cls)
            else:
                remaining.append(cls)

        return filtered, deferred, remaining
