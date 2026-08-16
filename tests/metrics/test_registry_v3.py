"""
词表注册中心 v3 约束边界测试（docs/词表体系重设计-修订版实施计划.md M1）

覆盖：
  1. 约束边界：加载报错保留（registry.yaml 缺失 / 注册词表文件缺失 -> fail-fast），
     内容与声明类校验宽容（版本号 warning / 非法元数据跳过或默认）；
     key 即文件名，消费方无未知 key 场景，不做专门处理
  2. 词条读取：去重保序、文件路径获取
  3. version_hash：确定性、与加载顺序无关、未加载词表也参与、文件改动后变化
  4. 双向约束：注册的 key 必须可加载（load 时全量校验文件存在）；
     加载的词表必须已注册（src/ 下词表读取只经 registry/tables，禁止硬编码路径）
  5. consumers 登记校验：每个 active 表目有 ≥1 个消费者且模块真实可导入
  6. 生产加载点（preprocess_helpers）走 tables 常量全部成功

注：count/file_hash 声明校验已按用户要求删除（词表内容可自由迭代），
相关用例不保留；词条数实时可查 registry.get() 长度。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import src
from src.lexicons.registry import LexiconRegistry
from src.workflows.preprocess_helpers import _load_all_lexicons_for_preprocess

# 加载路径断言中豁免的文件：registry 与 parser 自身实现、
# lexicon_metrics 的 load_weighted_lexicon 公共 API 包装（无硬编码路径，生产调用方
# 均为 registry/parser 或显式传路径的调用方）
_EXEMPT_FROM_PATH_ASSERT = {"registry.py", "lexicon_parser.py", "lexicon_metrics.py"}


@pytest.fixture()
def tmp_lexicon_dir(tmp_path: Path) -> Path:
    """构造最小合法 v3 词表目录（表目标识即文件名）"""
    (tmp_path / "registry.yaml").write_text(
        """\
version: "3.0"
lexicons:
  a.txt:
    kind: emotion
    tier: L1
    polarity: positive
    weight_policy: count
    consumers: ["workflows.preprocess_helpers"]
  combat.txt:
    kind: tension
    weight_policy: uniform
    consumers: ["workflows.preprocess_helpers"]
""",
        encoding="utf-8",
    )
    (tmp_path / "a.txt").write_text("快乐\n开心\n开心\n", encoding="utf-8")
    (tmp_path / "combat.txt").write_text("斩杀\n", encoding="utf-8")
    return tmp_path


def _write_registry(tmp_path: Path, content: str) -> None:
    (tmp_path / "registry.yaml").write_text(content, encoding="utf-8")


def _registry_yaml(
    entries: str,
    version: str = "3.0",
) -> str:
    return f'version: "{version}"\nlexicons:\n{entries}'


# ====================================================================
# 1. 约束边界：加载报错保留（fail-fast），内容/声明类校验宽容
# ====================================================================


class TestStrictValidation:
    def test_unknown_kind_skips_entry(self, tmp_path: Path) -> None:
        """非法 kind 宽容：该表目跳过，其余表目正常加载"""
        _write_registry(
            tmp_path,
            _registry_yaml(
                """\
  a.txt:
    kind: bogus_kind
  combat.txt:
    kind: tension
"""
            ),
        )
        (tmp_path / "a.txt").write_text("快乐\n", encoding="utf-8")
        (tmp_path / "combat.txt").write_text("斩杀\n", encoding="utf-8")
        reg = LexiconRegistry(base_dir=tmp_path)
        reg.load()  # 不 raise
        assert "a.txt" not in reg.list_all_keys()
        assert "combat.txt" in reg.list_all_keys()

    def test_bad_status_falls_back_to_active(self, tmp_path: Path) -> None:
        """非法 status 宽容：按 active 处理，可正常加载"""
        _write_registry(
            tmp_path,
            _registry_yaml(
                """\
  a.txt:
    kind: emotion
    status: archived
"""
            ),
        )
        (tmp_path / "a.txt").write_text("快乐\n", encoding="utf-8")
        reg = LexiconRegistry(base_dir=tmp_path)
        reg.load()
        assert reg.get("a.txt") == ["快乐"]

    def test_missing_file_raises_on_load(self, tmp_path: Path) -> None:
        """加载报错保留：注册词表的文件缺失 -> 加载即报错（fail-fast，防静默空跑）"""
        _write_registry(
            tmp_path,
            _registry_yaml(
                """\
  missing.txt:
    kind: emotion
"""
            ),
        )
        with pytest.raises(FileNotFoundError, match="missing.txt"):
            LexiconRegistry(base_dir=tmp_path).load()

    def test_missing_file_raises_on_get(self, tmp_lexicon_dir: Path) -> None:
        """加载报错保留：load 后词表文件被删，get 同样报错而非静默返回空"""
        reg = LexiconRegistry(base_dir=tmp_lexicon_dir)
        reg.load()
        (tmp_lexicon_dir / "a.txt").unlink()
        with pytest.raises(FileNotFoundError, match="a.txt"):
            reg.get("a.txt")

    def test_content_changes_do_not_raise(self, tmp_path: Path) -> None:
        """词表内容可自由迭代：改动词条不触发任何声明校验报错"""
        _write_registry(
            tmp_path,
            _registry_yaml(
                """\
  a.txt:
    kind: emotion
"""
            ),
        )
        (tmp_path / "a.txt").write_text("快乐\n", encoding="utf-8")
        reg = LexiconRegistry(base_dir=tmp_path)
        reg.load()
        (tmp_path / "a.txt").write_text("快乐\n开心\n新词条\n", encoding="utf-8")
        reg.load()  # 词表文件改动后重新加载不报错
        assert len(reg.get("a.txt")) == 3

    def test_registry_version_mismatch_tolerated(self, tmp_path: Path) -> None:
        """版本号宽容：不匹配仅 warning，按当前结构尽力解析"""
        _write_registry(
            tmp_path,
            _registry_yaml(
                """\
  a.txt:
    kind: emotion
""",
                version="2.0",
            ),
        )
        (tmp_path / "a.txt").write_text("快乐\n", encoding="utf-8")
        reg = LexiconRegistry(base_dir=tmp_path)
        reg.load()  # 不 raise
        assert reg.get("a.txt") == ["快乐"]

    def test_missing_registry_yaml_raises(self, tmp_path: Path) -> None:
        """加载报错保留：registry.yaml 缺失 -> 报错"""
        with pytest.raises(FileNotFoundError, match="registry.yaml"):
            LexiconRegistry(base_dir=tmp_path).load()


# ====================================================================
# 2. 词条读取
# ====================================================================


class TestLexiconLoading:
    def test_deduplicates_preserves_order(self, tmp_lexicon_dir: Path) -> None:
        reg = LexiconRegistry(base_dir=tmp_lexicon_dir)
        reg.load()
        # 文件内重复词条去重，保持首次出现顺序
        assert reg.get("a.txt") == ["快乐", "开心"]

    def test_get_file_paths(self, tmp_lexicon_dir: Path) -> None:
        reg = LexiconRegistry(base_dir=tmp_lexicon_dir)
        reg.load()
        assert reg.get_file_paths("a.txt") == [tmp_lexicon_dir / "a.txt"]

    def test_get_weighted(self, tmp_lexicon_dir: Path) -> None:
        reg = LexiconRegistry(base_dir=tmp_lexicon_dir)
        reg.load()
        assert reg.get_weighted("a.txt") == {"快乐": 1, "开心": 1}


# ====================================================================
# 3. version_hash：确定性、与加载状态无关
# ====================================================================


class TestVersionHashV3:
    def test_deterministic_across_loads(self, tmp_lexicon_dir: Path) -> None:
        h1 = LexiconRegistry(base_dir=tmp_lexicon_dir).version_hash()
        h2 = LexiconRegistry(base_dir=tmp_lexicon_dir).version_hash()
        assert h1 == h2

    def test_independent_of_load_order(self, tmp_lexicon_dir: Path) -> None:
        """未 get 过的词表同样参与 hash——与加载顺序/加载集合无关"""
        reg_a = LexiconRegistry(base_dir=tmp_lexicon_dir)
        reg_a.load()
        h1 = reg_a.version_hash()

        reg_b = LexiconRegistry(base_dir=tmp_lexicon_dir)
        reg_b.load()
        reg_b.get("combat.txt")  # 只加载子集
        h2 = reg_b.version_hash()
        assert h1 == h2

    def test_changes_when_file_changes(self, tmp_lexicon_dir: Path) -> None:
        h1 = LexiconRegistry(base_dir=tmp_lexicon_dir).version_hash()
        (tmp_lexicon_dir / "a.txt").write_text("快乐\n开心\n新词条\n", encoding="utf-8")
        h2 = LexiconRegistry(base_dir=tmp_lexicon_dir).version_hash()
        assert h1 != h2

    def test_covers_unloaded_lexicon_files(self, tmp_path: Path) -> None:
        """未加载词表的文件内容参与 hash：改动未加载词表后 hash 变化"""
        (tmp_path / "registry.yaml").write_text(
            _registry_yaml(
                """\
  a.txt:
    kind: emotion
    consumers: ["workflows.preprocess_helpers"]
  b.txt:
    kind: emotion
    polarity: negative
    consumers: ["workflows.preprocess_helpers"]
"""
            ),
            encoding="utf-8",
        )
        (tmp_path / "a.txt").write_text("快乐\n", encoding="utf-8")
        (tmp_path / "b.txt").write_text("悲伤\n", encoding="utf-8")

        reg = LexiconRegistry(base_dir=tmp_path)
        reg.load()
        reg.get("a.txt")  # 仅加载 a.txt
        h1 = reg.version_hash()

        (tmp_path / "b.txt").write_text("悲伤\n绝望\n", encoding="utf-8")
        h2 = LexiconRegistry(base_dir=tmp_path).version_hash()
        assert h2 != h1  # 未加载的 b.txt 文件改动也入 hash


# ====================================================================
# 4. 双向约束：注册的 key 必须可加载；加载的词表必须已注册
# ====================================================================


class TestRegistryIsSingleSourceOfTruth:
    def test_all_active_keys_loadable(self) -> None:
        """注册的 key 必须可加载（生产注册表，load 即全量校验）"""
        reg = LexiconRegistry()
        reg.load()
        for key in reg.list_all_keys():
            spec = reg.specs[key]
            if spec.status == "active":
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


# ====================================================================
# 5. consumers 登记校验
# ====================================================================


class TestConsumersRegistered:
    def test_active_lexicons_have_real_consumers(self) -> None:
        """每个 active 表目有 ≥1 个 consumers 且模块真实可导入"""
        reg = LexiconRegistry()
        reg.load()
        for key, spec in reg.specs.items():
            if spec.status != "active":
                continue
            assert spec.consumers, f"词表 {key} 未登记任何消费者"
            for consumer in spec.consumers:
                # registry.yaml 中的 consumers 为 src 内模块名（不带 src. 前缀）
                importlib.import_module(f"src.{consumer}")  # 消费者模块必须真实存在
