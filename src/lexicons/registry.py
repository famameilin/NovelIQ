"""
词表注册中心 (Lexicon Registry v3)

注册关系唯一事实源：src/config/constants/lexicons.py 的 LEXICON_FILES
（语义 key -> 文件名），注册文件集合即其全部文件名。

设计（2026-08-15 按用户要求）：
  - 表目标识即文件名（data/lexicons/ 下无语义 key 层）。
  - 消费方经 LEXICON_FILES["key"] 引用文件名，不写魔法字符串。
  - 加载报错保留（fail-fast）：注册词表文件缺失 -> 加载即报错，防止分析链
    静默拿到空词表降级；词表是否参与正式指标由调用方决定（用/不用）。
  - 词表内容可自由迭代：词条增删不触发任何声明校验。
  - version_hash 为与加载状态无关的确定性 hash：
    覆盖注册文件名集合 canonical JSON + 全部注册文件原文

使用方式::

    from src.config.constants import LEXICON_FILES

    reg = LexiconRegistry()
    pos_terms = reg.get(LEXICON_FILES["positive"])               # 词条列表
    pos_weighted = reg.get_weighted(LEXICON_FILES["positive"])    # 加权 dict（M4 弃用权重前过渡用）
    sem_files = reg.get_file_paths(LEXICON_FILES["semantic_category"])
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from src.config.constants import LEXICON_FILES
from src.utils.lexicon_parser import load_lexicon_terms, load_weighted_lexicon

_DEFAULT_LEXICON_DIR = Path("data/lexicons")


class LexiconRegistry:
    """登记式词表注册中心（key 即文件名；加载报错保留，词表内容可自由迭代）"""

    def __init__(self, base_dir: Path | str | None = None, registry_files: list[str] | None = None) -> None:
        """
        base_dir 为词表目录、registry_files 为注册文件集合（测试注入）；
        缺省分别为 data/lexicons 与 constants.LEXICON_FILES 全部文件名。
        """
        self._base_dir = Path(base_dir) if base_dir else _DEFAULT_LEXICON_DIR
        self._injected_registry_files = registry_files
        self._registry_files: list[str] = []
        self._cache: dict[str, list[str]] = {}
        self._weighted_cache: dict[str, dict[str, int]] = {}
        self._loaded = False

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """加载注册文件集合；注册词表文件缺失 -> 报错（fail-fast，防静默空跑）"""
        if self._injected_registry_files is not None:
            self._registry_files = sorted(self._injected_registry_files)
        else:
            self._registry_files = sorted(LEXICON_FILES.values())
        for key in self._registry_files:
            path = self._base_dir / key
            if not path.exists():
                raise FileNotFoundError(f"词表 '{key}' 的文件缺失: {path}")
        self._loaded = True
        logger.info("LexiconRegistry loaded: base_dir={}, lexicons={}", self._base_dir, len(self._registry_files))

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

    def version_hash(self) -> str:
        """
        当前词表版本的摘要（哈希已删除，返回空串）
        """
        self.ensure_loaded()
        return ""

    def list_all_keys(self) -> list[str]:
        """列出所有已注册的词表 key（文件名）"""
        self.ensure_loaded()
        return list(self._registry_files)


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
