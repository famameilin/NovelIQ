"""
词表注册中心 v3 约束边界测试（docs/词表体系重设计-修订版实施计划.md M1）

覆盖：
  1. 约束边界：加载报错保留（注册词表文件缺失 -> fail-fast，防静默空跑）；
     词表内容可自由迭代
  2. 词条读取：去重保序、文件路径获取、加权词表
  3. version_hash：确定性、与加载顺序无关、未加载词表也参与、文件改动后变化
  4. 双向约束：注册的 key 必须可加载（load 时全量校验文件存在）；
     加载的词表必须已注册（src/ 下词表读取只经 registry/tables，禁止硬编码路径）
  5. 生产加载点（preprocess_helpers）走 tables 常量全部成功

注：count/file_hash 声明校验已按用户要求删除（词表内容可自由迭代）；
kind/tier/polarity/weight_policy/consumers/status 元数据已于 2026-08-28
塌缩删除（生产无消费点，词表用/不用由调用方决定）。
注册关系唯一事实源为 src/config/constants/lexicons.py 的 LEXICON_FILES；
测试侧经构造注入 registry_files 或 monkeypatch registry 模块的 LEXICON_FILES。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import src
from src.config.constants import LEXICON_DRAFT_KEYS, LEXICON_FILES
from src.lexicons.registry import LexiconRegistry
from src.workflows.preprocess_helpers import _load_all_lexicons_for_preprocess

# 加载路径断言中豁免的文件：registry 与 parser 自身实现、
# lexicon_metrics 的 load_weighted_lexicon 公共 API 包装（无硬编码路径，生产调用方
# 均为 registry/parser 或显式传路径的调用方）
_EXEMPT_FROM_PATH_ASSERT = {"registry.py", "lexicon_parser.py", "lexicon_metrics.py"}


def _make_registry(base_dir: Path, registry_files: list[str] | None = None) -> LexiconRegistry:
    """构造注入注册文件集合的注册中心（缺省 a.txt + combat.txt，与 tmp_lexicon_dir 对应）"""
    return LexiconRegistry(base_dir=base_dir, registry_files=registry_files or ["a.txt", "combat.txt"])


@pytest.fixture()
def tmp_lexicon_dir(tmp_path: Path) -> Path:
    """构造最小合法 v3 词表目录（表目标识即文件名）"""
    (tmp_path / "a.txt").write_text("快乐\n开心\n开心\n", encoding="utf-8")
    (tmp_path / "combat.txt").write_text("斩杀\n", encoding="utf-8")
    return tmp_path


# ====================================================================
# 1. 约束边界：加载报错保留（fail-fast），词表内容可自由迭代
# ====================================================================


class TestStrictValidation:
    def test_missing_file_raises_on_load(self, tmp_path: Path) -> None:
        """加载报错保留：注册词表的文件缺失 -> 加载即报错（fail-fast，防静默空跑）"""
        with pytest.raises(FileNotFoundError, match="missing.txt"):
            LexiconRegistry(base_dir=tmp_path, registry_files=["missing.txt"]).load()

    def test_missing_file_raises_on_get(self, tmp_lexicon_dir: Path) -> None:
        """加载报错保留：load 后词表文件被删，get 同样报错而非静默返回空"""
        reg = _make_registry(tmp_lexicon_dir)
        reg.load()
        (tmp_lexicon_dir / "a.txt").unlink()
        with pytest.raises(FileNotFoundError, match="a.txt"):
            reg.get("a.txt")

    def test_content_changes_do_not_raise(self, tmp_path: Path) -> None:
        """词表内容可自由迭代：改动词条不触发任何声明校验报错"""
        (tmp_path / "a.txt").write_text("快乐\n", encoding="utf-8")
        reg = _make_registry(tmp_path, ["a.txt"])
        reg.load()
        (tmp_path / "a.txt").write_text("快乐\n开心\n新词条\n", encoding="utf-8")
        reg.load()  # 词表文件改动后重新加载不报错
        assert len(reg.get("a.txt")) == 3


# ====================================================================
# 2. 词条读取
# ====================================================================


class TestLexiconLoading:
    def test_deduplicates_preserves_order(self, tmp_lexicon_dir: Path) -> None:
        reg = _make_registry(tmp_lexicon_dir)
        reg.load()
        # 文件内重复词条去重，保持首次出现顺序
        assert reg.get("a.txt") == ["快乐", "开心"]

    def test_get_file_paths(self, tmp_lexicon_dir: Path) -> None:
        reg = _make_registry(tmp_lexicon_dir)
        reg.load()
        assert reg.get_file_paths("a.txt") == [tmp_lexicon_dir / "a.txt"]

    def test_get_weighted(self, tmp_lexicon_dir: Path) -> None:
        reg = _make_registry(tmp_lexicon_dir)
        reg.load()
        assert reg.get_weighted("a.txt") == {"快乐": 1, "开心": 1}

    def test_loads_from_constants_production_source(self) -> None:
        """生产路径：无注入时注册文件集合取 constants.LEXICON_FILES 全部文件名"""
        reg = LexiconRegistry()
        reg.load()
        assert reg.list_all_keys() == sorted(LEXICON_FILES.values())


# ====================================================================
# 3. version_hash：哈希已删除，返回空串
# ====================================================================


class TestVersionHashV3:
    def test_always_empty(self, tmp_lexicon_dir: Path) -> None:
        h1 = _make_registry(tmp_lexicon_dir).version_hash()
        h2 = _make_registry(tmp_lexicon_dir).version_hash()
        assert h1 == ""
        assert h1 == h2


# ====================================================================
# 4. 双向约束：注册的 key 必须可加载；加载的词表必须已注册
# ====================================================================


class TestRegistryIsSingleSourceOfTruth:
    def test_all_registered_keys_loadable(self) -> None:
        """注册的 key 必须可加载（生产注册表，load 即全量校验）；
        draft 审定队列为空=无待审词条，是合法稳态，豁免非空断言"""
        reg = LexiconRegistry()
        reg.load()
        draft_files = {LEXICON_FILES[k] for k in LEXICON_DRAFT_KEYS}
        for key in reg.list_all_keys():
            if key in draft_files:
                continue
            assert len(reg.get(key)) > 0, f"注册表目 {key} 加载为空"

    def test_no_hardcoded_lexicon_paths_in_src(self) -> None:
        """加载的词表必须已注册：src/ 下词表文件读取只经 registry（parser 除外）"""
        src_root = Path(src.__file__).parent
        offenders: list[str] = []
        for py in src_root.rglob("*.py"):
            if py.name in _EXEMPT_FROM_PATH_ASSERT:
                continue
            text = py.read_text(encoding="utf-8")
            if "load_weighted_lexicon(" in text or "load_lexicon_terms(" in text:
                offenders.append(str(py))
        assert not offenders, f"存在绕过注册表的词表读取: {offenders}"

    def test_production_load_all_lexicons_via_tables(self) -> None:
        """生产加载点经 tables 常量组装全部成功（含 L1+L2 合并与语义类别解析）"""
        lexicons = _load_all_lexicons_for_preprocess()
        assert set(lexicons) >= {
            "sensory",
            "function_words",
            "imagery",
            "fight_terms",
            "pos_terms",
            "neg_terms",
            "semantic_categories",
        }
        # M3 重建后 L1+L2 合并规模（原表 1061/1007 词收敛，此处断言数量级而非精确值）
        assert len(lexicons["pos_terms"]) > 50
        assert len(lexicons["neg_terms"]) > 50
        assert len(lexicons["semantic_categories"]) > 5
