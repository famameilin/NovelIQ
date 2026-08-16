"""
词表注册中心 (Lexicon Registry v3)

基于 registry.yaml 的登记式词表加载系统，唯一事实源。

设计（2026-08-15 按用户要求）：
  - 表目标识即文件名（data/lexicons/ 下无语义 key 层），元数据登记
    kind / status / weight_policy / consumers。
  - 消费方经 src.config.constants 的 LEXICON_* 常量引用文件名，不写魔法字符串。
  - 加载报错保留（fail-fast）：registry.yaml 缺失、注册词表文件缺失 -> 加载即报错，
    防止分析链静默拿到空词表降级。
  - 内容与声明类校验宽容：版本号不符 / 非法元数据（kind/status/weight_policy）
    / consumers 异常 -> warning + 空结果/默认值，词表与注册表可自由迭代；
    count/file_hash 声明校验已删除。
  - version_hash 为与加载状态无关的确定性 hash：
    覆盖 registry.yaml + conflict_matrix.yaml + 全部注册文件原文
  - consumers 登记真实消费点（信息性字段，由测试侧校验登记完整性）

使用方式::

    reg = LexiconRegistry()
    pos_terms = reg.get(LEXICON_POSITIVE)               # 词条列表
    pos_weighted = reg.get_weighted(LEXICON_POSITIVE)    # 加权 dict（M4 弃用权重前过渡用）
    sem_files = reg.get_file_paths(LEXICON_SEMANTIC_CATEGORY)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from src.utils.lexicon_parser import load_lexicon_terms, load_weighted_lexicon

_DEFAULT_LEXICON_DIR = Path("data/lexicons")
_REGISTRY_FILE = "registry.yaml"
_CONFLICT_MATRIX_FILE = "conflict_matrix.yaml"
_REGISTRY_VERSION = "3.0"

_ALLOWED_KINDS = frozenset({"emotion", "tension", "style", "tokenizer"})
_ALLOWED_STATUSES = frozenset({"active", "deprecated"})
_ALLOWED_WEIGHT_POLICIES = frozenset({"weighted", "uniform", "count"})


@dataclass(frozen=True)
class LexiconSpec:
    """词表表目（registry.yaml 单条记录的解析结果；key 即 data/lexicons 下的文件名）"""

    key: str
    kind: str
    consumers: tuple[str, ...] = ()
    status: str = "active"
    weight_policy: str = "uniform"
    tier: str | None = None
    polarity: str | None = None
    description: str = ""


class LexiconRegistry:
    """登记式词表注册中心（key 即文件名；加载报错保留，内容/声明类校验宽容）"""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self._base_dir = Path(base_dir) if base_dir else _DEFAULT_LEXICON_DIR
        self._specs: dict[str, LexiconSpec] = {}
        self._conflicts: list[dict[str, Any]] = []
        self._cache: dict[str, list[str]] = {}
        self._weighted_cache: dict[str, dict[str, int]] = {}
        self._loaded = False

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def specs(self) -> dict[str, LexiconSpec]:
        """已登记的全部表目（只读快照）"""
        return dict(self._specs)

    def load(self) -> None:
        """加载注册表与冲突矩阵；注册表缺失 / 注册词表文件缺失 -> 报错（fail-fast）"""
        self._load_registry()
        self._load_conflict_matrix()
        for key, spec in self._specs.items():
            if spec.status == "active":
                self._validate_file(key, spec)
        self._loaded = True
        logger.info(
            "LexiconRegistry loaded: base_dir={}, lexicons={}, conflicts={}",
            self._base_dir,
            len(self._specs),
            len(self._conflicts),
        )

    def ensure_loaded(self) -> None:
        """延迟加载（首次调用时加载）"""
        if not self._loaded:
            self.load()

    def get(self, key: str) -> list[str]:
        """
        获取词表词条（key 即文件名，去重保序）

        key 均为代码内写死的注册表目（无未知 key 场景，不做专门处理）；
        词表文件缺失：报错（fail-fast）。
        """
        self.ensure_loaded()
        if key in self._cache:
            return self._cache[key]

        path = self._base_dir / key
        if not path.exists():
            raise FileNotFoundError(f"词表 '{key}' 的文件缺失: {path}")
        terms = load_lexicon_terms(path)

        seen: set[str] = set()
        deduped: list[str] = []
        for term in terms:
            if term not in seen:
                seen.add(term)
                deduped.append(term)
        self._cache[key] = deduped
        return deduped

    def get_weighted(self, key: str) -> dict[str, int]:
        """
        获取加权词表（"词条\\t权重" 格式；纯词条按默认权重 1）

        key 均为代码内写死的注册表目（无未知 key 场景，不做专门处理）；
        词表文件缺失：报错（fail-fast）。
        """
        self.ensure_loaded()
        if key in self._weighted_cache:
            return self._weighted_cache[key]

        path = self._base_dir / key
        if not path.exists():
            raise FileNotFoundError(f"词表 '{key}' 的文件缺失: {path}")
        merged = load_weighted_lexicon(path)
        self._weighted_cache[key] = merged
        return merged

    def get_file_paths(self, key: str) -> list[Path]:
        """返回词表文件路径（如 semantic_category 的类别解析需要原文）；文件缺失报错"""
        self.ensure_loaded()
        path = self._base_dir / key
        if not path.exists():
            raise FileNotFoundError(f"词表 '{key}' 的文件缺失: {path}")
        return [path]

    def get_conflicts_for(self, key: str) -> list[dict[str, Any]]:
        """获取指定词表的跨表冲突声明（仅审计用途，不影响加载结果）"""
        self.ensure_loaded()
        return [c for c in self._conflicts if c.get("primary") == key or key in c.get("referenced_by", [])]

    def version_hash(self) -> str:
        """
        当前词表版本的 SHA256 摘要（与加载状态无关的确定性 hash）

        覆盖：registry.yaml 原文 + conflict_matrix.yaml 原文 + 每个注册文件全文
        （缺失文件跳过）。未加载/从未 get 过的词表同样参与 hash。
        """
        self.ensure_loaded()
        hasher = hashlib.sha256()
        reg_path = self._base_dir / _REGISTRY_FILE
        if reg_path.exists():
            hasher.update(reg_path.read_bytes())
        conflict_path = self._base_dir / _CONFLICT_MATRIX_FILE
        if conflict_path.exists():
            hasher.update(conflict_path.read_bytes())
        for key in sorted(self._specs):
            path = self._base_dir / key
            hasher.update(f"{key}:".encode())
            if path.exists():
                hasher.update(path.read_bytes())
        return hasher.hexdigest()[:16]

    def list_all_keys(self) -> list[str]:
        """列出所有已登记的词表 key（文件名）"""
        self.ensure_loaded()
        return sorted(self._specs)

    def _load_registry(self) -> None:
        path = self._base_dir / _REGISTRY_FILE
        if not path.exists():
            raise FileNotFoundError(f"registry.yaml not found at {path}")

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        version = raw.get("version")
        if version != _REGISTRY_VERSION:
            logger.warning(
                "registry.yaml 版本 {!r} 与期望 {!r} 不符，按当前结构尽力解析",
                version,
                _REGISTRY_VERSION,
            )
        for key, data in raw.get("lexicons", {}).items():
            spec = self._parse_spec(key, data)
            if spec is not None:
                self._specs[key] = spec

    def _validate_file(self, key: str, spec: LexiconSpec) -> None:
        """校验词表文件存在（fail-fast：加载不存在的词表报错，防静默空跑）"""
        path = self._base_dir / key
        if not path.exists():
            raise FileNotFoundError(f"词表 '{key}' 的文件缺失: {path}")

    @staticmethod
    def _parse_spec(key: str, data: Any) -> LexiconSpec | None:
        """宽容解析：非法表目仅 warning + 跳过/默认，不 raise"""
        if not isinstance(data, dict):
            logger.warning("词表 '{}' 的表目不是 mapping，跳过", key)
            return None

        kind = data.get("kind")
        if kind not in _ALLOWED_KINDS:
            logger.warning("词表 '{}' 的 kind 非法 {!r}，跳过", key, kind)
            return None

        status = data.get("status", "active")
        if status not in _ALLOWED_STATUSES:
            logger.warning("词表 '{}' 的 status 非法 {!r}，按 active 处理", key, status)
            status = "active"

        weight_policy = data.get("weight_policy", "uniform")
        if weight_policy not in _ALLOWED_WEIGHT_POLICIES:
            logger.warning("词表 '{}' 的 weight_policy 非法 {!r}，按 uniform 处理", key, weight_policy)
            weight_policy = "uniform"

        consumers = data.get("consumers", [])
        if isinstance(consumers, str):
            consumers = [consumers]
        if not isinstance(consumers, list) or not all(isinstance(c, str) and c for c in consumers):
            logger.warning("词表 '{}' 的 consumers 非法，按空处理", key)
            consumers = []

        return LexiconSpec(
            key=key,
            kind=kind,
            consumers=tuple(consumers),
            status=status,
            weight_policy=weight_policy,
            tier=data.get("tier"),
            polarity=data.get("polarity"),
            description=data.get("description", ""),
        )

    def _load_conflict_matrix(self) -> None:
        """读取 conflict_matrix.yaml（仅审计声明，不参与加载逻辑）"""
        path = self._base_dir / _CONFLICT_MATRIX_FILE
        if not path.exists():
            logger.debug("conflict_matrix.yaml not found, no overlap tracking")
            self._conflicts = []
            return

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            self._conflicts = data.get("conflicts", [])


_global_registry: LexiconRegistry | None = None


def get_registry(base_dir: Path | str | None = None) -> LexiconRegistry:
    """获取全局词表注册中心单例"""
    global _global_registry
    if _global_registry is None:
        _global_registry = LexiconRegistry(base_dir=base_dir)
    return _global_registry


def reset_registry() -> None:
    """重置全局单例（测试用）"""
    global _global_registry
    _global_registry = None
