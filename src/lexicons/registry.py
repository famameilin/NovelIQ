"""
词表注册中心 (Lexicon Registry v2)

基于 registry.yaml + conflict_matrix.yaml 的分层词表加载系统。

核心能力:
  - 从 registry.yaml 读取词表分层归属与元信息
  - 从 conflict_matrix.yaml 加载跨表冲突声明
  - 支持领域扩展词表（domain/ 子目录）的增量叠加
  - 支持排除借用词（exclude_borrowed）避免重复计数
  - 提供版本 hash 用于报告和审计

使用方式::

    reg = LexiconRegistry()
    pos_terms = reg.get("emotion.positive")           # 基础词表
    neg_ext = reg.get_with_domains("emotion.negative", ["xianxia"])  # 带修仙扩展

"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from loguru import logger

from src.utils.lexicon_parser import load_lexicon_terms, load_weighted_lexicon

if TYPE_CHECKING:
    from src.workflows.curve_metrics import WeightedLexiconSet

_DEFAULT_LEXICON_DIR = Path("data/lexicons")
_REGISTRY_FILE = "registry.yaml"
_CONFLICT_MATRIX_FILE = "conflict_matrix.yaml"
_DOMAIN_DIR = "domain"


class LexiconRegistry:
    """分层词表注册中心"""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self._base_dir = Path(base_dir) if base_dir else _DEFAULT_LEXICON_DIR
        self._registry: dict[str, Any] = {}
        self._conflicts: list[dict[str, Any]] = []
        self._cache: dict[str, list[str]] = {}
        self._domain_cache: dict[str, list[str]] = {}
        self._loaded = False

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """加载注册表与冲突矩阵"""
        self._load_registry()
        self._load_conflict_matrix()
        self._loaded = True
        logger.info(
            "LexiconRegistry loaded: base_dir={}, layers={}, conflicts={}",
            self._base_dir,
            len(self._registry.get("layers", {})),
            len(self._conflicts),
        )

    def ensure_loaded(self) -> None:
        """延迟加载（首次调用时加载）"""
        if not self._loaded:
            self.load()

    def get(self, key: str, exclude_borrowed: bool = False) -> list[str]:
        """
        获取指定词表。

        Args:
            key: 词表标识，格式 "layer.lexicon"，如 "emotion.positive"
            exclude_borrowed: 是否排除被其他表借用的词条

        Returns:
            词条列表
        """
        self.ensure_loaded()

        if key in self._cache and not exclude_borrowed:
            return self._cache[key]

        terms = self._load_lexicon_file(key)

        if exclude_borrowed:
            terms = self._exclude_borrowed(key, terms)

        self._cache[key] = terms
        return terms

    def get_with_domains(
        self, key: str, domain_tags: list[str] | None = None, exclude_borrowed: bool = False
    ) -> list[str]:
        """
        获取词表 + 领域扩展。

        基础词表与 domain 扩展的并集去重，domain 是增量叠加而非替换。

        Args:
            key: 词表标识
            domain_tags: 领域标签列表，如 ["xianxia", "shuwen"]
            exclude_borrowed: 是否排除借用词
        """
        base_terms = self.get(key, exclude_borrowed=exclude_borrowed)

        if not domain_tags:
            return base_terms

        cache_key = f"{key}+{','.join(sorted(domain_tags))}"
        if cache_key in self._domain_cache:
            return self._domain_cache[cache_key]

        extended = set(base_terms)
        for tag in domain_tags:
            domain_terms = self._load_domain_lexicon(tag)
            if domain_terms:
                extended.update(domain_terms)
                logger.debug("Domain '{}' added {} terms to '{}'", tag, len(domain_terms), key)

        result = sorted(extended)
        self._domain_cache[cache_key] = result
        return result

    def get_conflicts_for(self, key: str) -> list[dict[str, Any]]:
        """获取指定词表的跨表冲突声明"""
        self.ensure_loaded()
        return [c for c in self._conflicts if c.get("primary") == key or key in c.get("referenced_by", [])]

    def version_hash(self) -> str:
        """计算当前词表版本的 SHA256 摘要（用于报告和审计）"""
        self.ensure_loaded()
        hasher = hashlib.sha256()

        hasher.update(yaml.safe_dump(self._registry).encode())

        for key in sorted(self._cache.keys()):
            terms_str = ",".join(self._cache[key])
            hasher.update(f"{key}:{terms_str}".encode())

        hasher.update(yaml.safe_dump(self._conflicts).encode())

        return hasher.hexdigest()[:16]

    def list_all_keys(self) -> list[str]:
        """列出所有已注册的词表 key（layer.lexicon 格式）"""
        self.ensure_loaded()
        keys = []
        for layer_name, layer_data in self._registry.get("layers", {}).items():
            for lex_name in layer_data.get("lexicons", {}):
                keys.append(f"{layer_name}.{lex_name}")
        return keys

    def _load_registry(self) -> None:
        """读取 registry.yaml"""
        path = self._base_dir / _REGISTRY_FILE
        if not path.exists():
            logger.warning("registry.yaml not found at {}, using empty registry", path)
            self._registry = {"layers": {}, "version": "1.0-fallback"}
            return

        with open(path, encoding="utf-8") as f:
            self._registry = yaml.safe_load(f) or {}

    def _load_conflict_matrix(self) -> None:
        """读取 conflict_matrix.yaml"""
        path = self._base_dir / _CONFLICT_MATRIX_FILE
        if not path.exists():
            logger.debug("conflict_matrix.yaml not found, no overlap tracking")
            self._conflicts = []
            return

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            self._conflicts = data.get("conflicts", [])

    def _resolve_file_path(self, key: str) -> Path | None:
        """从 key 解析出 .txt 文件路径"""
        parts = key.split(".", 1)
        if len(parts) != 2:
            return None

        layer_name, lex_name = parts
        layer_data = self._registry.get("layers", {}).get(layer_name, {})
        lexicon_info = layer_data.get("lexicons", {}).get(lex_name, {})
        file_name = lexicon_info.get("file")

        if file_name:
            return self._base_dir / file_name

        return self._base_dir / f"{lex_name}.txt"

    def _load_lexicon_file(self, key: str) -> list[str]:
        """
        从 .txt 文件加载原始词条。

        支持两种格式：
        - 纯词条格式：每行一个词条
        - 加权格式：每行 "词条\\t权重"，只取词条部分


        """
        path = self._resolve_file_path(key)
        if path is None or not path.exists():
            logger.warning("Lexicon file not found for key='{}': {}", key, path)
            return []

        return load_lexicon_terms(path)

    def _load_domain_lexicon(self, tag: str) -> list[str]:
        """
        加载领域扩展词表。

        支持两种格式：
        - 纯词条格式：每行一个词条
        - 加权格式：每行 "词条\\t权重"，只取词条部分


        """
        domain_dir = self._base_dir / _DOMAIN_DIR
        path = domain_dir / f"{tag}.txt"
        if not path.exists():
            logger.debug("Domain lexicon '{}' not found: {}", tag, path)
            return []

        return load_lexicon_terms(path)

    def _exclude_borrowed(self, primary_key: str, terms: list[str]) -> list[str]:
        """
        排除被声明为「从主属表借用」的词条。

        当 A 表是某词条的主属表、B 表只是借用时，
        如果调用方请求 B 表且 exclude_borrowed=True，
        则该词条从 B 的返回结果中移除。

        """
        borrowed: set[str] = set()

        for entry in self._conflicts:
            if primary_key in entry.get("referenced_by", []):
                borrowed.add(entry["term"])

        if not borrowed:
            return terms

        filtered = [t for t in terms if t not in borrowed]
        if len(filtered) != len(terms):
            logger.debug(
                "Excluded {} borrowed terms from '{}'",
                len(terms) - len(filtered),
                primary_key,
            )

        return filtered


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


def get_weighted_lexicon_set(
    registry: LexiconRegistry,
    pos_domains: list[str] | None = None,
    neg_domains: list[str] | None = None,
    fight_domains: list[str] | None = None,
) -> WeightedLexiconSet:
    """
    获取完整的加权词表集合。

    使用 load_weighted_lexicon 加载词典。

    """
    from src.workflows.curve_metrics import WeightedLexiconSet

    pos_terms = load_weighted_lexicon(str(registry.base_dir / "positive.txt"))
    neg_terms = load_weighted_lexicon(str(registry.base_dir / "negative.txt"))
    fight_terms = load_weighted_lexicon(str(registry.base_dir / "combat.txt"))

    if pos_domains:
        for tag in pos_domains:
            domain_file = registry.base_dir / "domain" / f"{tag}.txt"
            if domain_file.exists():
                domain_terms = load_weighted_lexicon(str(domain_file))
                pos_terms.update(domain_terms)

    if neg_domains:
        for tag in neg_domains:
            domain_file = registry.base_dir / "domain" / f"{tag}.txt"
            if domain_file.exists():
                domain_terms = load_weighted_lexicon(str(domain_file))
                neg_terms.update(domain_terms)

    if fight_domains:
        for tag in fight_domains:
            domain_file = registry.base_dir / "domain" / f"{tag}.txt"
            if domain_file.exists():
                domain_terms = load_weighted_lexicon(str(domain_file))
                fight_terms.update(domain_terms)

    return WeightedLexiconSet(
        pos_terms=pos_terms,
        neg_terms=neg_terms,
        fight_terms=fight_terms,
    )
