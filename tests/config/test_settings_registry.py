"""2026-09-10 设置注册表与 settings 热生效工具的闸门测试

覆盖：
- 注册表↔dataclass 双向校验（防漂移，同 METRIC_CONTRACTS 闸门哲学）
- diff_user_overrides 稀疏化（含开放键空间 dict 例外）
- apply_settings_onto 原地热生效（单例身份不变）
- env_file 白名单编辑器（保注释保序 / 删除 / 追加 / 白名单违规）
"""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import fields
from pathlib import Path

import pytest

from src.config.env_file import EnvFileError, apply_env_updates_to_process, update_env_file
from src.config.settings import (
    Settings,
    apply_settings_onto,
    diff_user_overrides,
    serialize_settings,
)
from src.config.settings_registry import (
    MODEL_ENV_KEYS,
    SETTING_FIELD_TYPES,
    SETTING_FIELDS,
    SETTING_SECTIONS,
)

_TYPE_CHECKS: dict[str, tuple[type, ...]] = {
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "enum": (str,),
    "string": (str,),
}


def _resolve_in_defaults(spec_path: tuple[str, ...]) -> tuple[object | None, bool]:
    """沿 path 解析默认值。

    返回 (值, 是否封闭)。defaults 侧途中遇到空 dict（开放键空间，
    如 logging.modules 的模块名可增删）时后续段不属于代码固有结构，
    视为开放路径，值返回 None。
    """
    current: object = serialize_settings(Settings())
    for segment in spec_path:
        assert isinstance(current, dict), f"{'/'.join(spec_path)} 在默认值中缺层: {segment}"
        if segment not in current:
            assert current == {}, f"{'/'.join(spec_path)} 在默认值中不存在（且父层非开放键空间）"
            return None, False
        current = current[segment]
    return current, True


class TestRegistryContract:
    def test_every_field_resolves_in_defaults(self) -> None:
        """封闭字段必须能在 dataclass 默认值中解析到叶子（双向闸门正向）"""
        for spec in SETTING_FIELDS:
            value, closed = _resolve_in_defaults(spec.path)
            if not closed:
                continue
            assert value is not None or spec.nullable, f"{'/'.join(spec.path)} 解析到 None"
            assert not isinstance(value, dict), f"{'/'.join(spec.path)} 解析到 dict 而非叶子"

    def test_every_field_value_matches_declared_type(self) -> None:
        """封闭字段的默认值类型与声明类型一致（闸门反向：类型漂移时快速失败）"""
        for spec in SETTING_FIELDS:
            value, closed = _resolve_in_defaults(spec.path)
            if not closed:
                continue
            if spec.nullable and value is None:
                continue
            assert isinstance(value, _TYPE_CHECKS[spec.field_type]), (
                f"{'/'.join(spec.path)} 声明 {spec.field_type}，实际 {type(value).__name__}"
            )

    def test_enum_fields_have_values(self) -> None:
        for spec in SETTING_FIELDS:
            if spec.field_type == "enum":
                assert spec.enum_values, f"{'/'.join(spec.path)} 是 enum 但未声明可选值"

    def test_sections_cover_field_top_level_keys(self) -> None:
        section_ids = {section.id for section in SETTING_SECTIONS}
        for spec in SETTING_FIELDS:
            assert spec.path[0] in section_ids, f"{'/'.join(spec.path)} 不属于任何分区"

    def test_field_types_known(self) -> None:
        for spec in SETTING_FIELDS:
            assert spec.field_type in SETTING_FIELD_TYPES

    def test_no_credential_fields_in_registry(self) -> None:
        """凭据字段不进注册表：凭据只存 .env，由 /env 通道单独处理"""
        forbidden = {"base_url", "model", "api_key"}
        for spec in SETTING_FIELDS:
            assert spec.path[-1] not in forbidden, f"{'/'.join(spec.path)} 凭据字段不得进注册表"

    def test_settings_dataclass_fields_all_serialized(self) -> None:
        """Settings 的每个 dataclass 字段都出现在序列化结果中"""
        serialized = serialize_settings(Settings())
        for field_info in fields(Settings):
            assert field_info.name in serialized


class TestDiffUserOverrides:
    def test_keeps_only_differences(self) -> None:
        defaults = {"a": 1, "nested": {"x": 1, "y": 2}}
        effective = {"a": 1, "nested": {"x": 9, "y": 2}}
        assert diff_user_overrides(effective, defaults) == {"nested": {"x": 9}}

    def test_drops_unknown_keys(self) -> None:
        assert diff_user_overrides({"unknown": 1, "a": 2}, {"a": 1}) == {"a": 2}

    def test_open_dict_kept_whole(self) -> None:
        """defaults 侧为空 dict 时视为开放键空间（logging.modules），整体保留"""
        defaults = {"logging": {"modules": {}}}
        effective = {"logging": {"modules": {"src.api": {"file": "api.log"}}}}
        assert diff_user_overrides(effective, defaults) == effective

    def test_empty_open_dict_dropped(self) -> None:
        assert diff_user_overrides({"m": {}}, {"m": {}}) == {}

    def test_none_vs_default(self) -> None:
        assert diff_user_overrides({"a": None}, {"a": 1}) == {"a": None}


class TestApplySettingsOnto:
    def test_mutates_in_place(self) -> None:
        target = Settings()
        source = Settings()
        source.models.annotation.temperature = 1.5
        source.topic_model.num_topics = 7

        apply_settings_onto(target, source)

        assert target is not source
        assert target.models.annotation.temperature == 1.5
        assert target.topic_model.num_topics == 7

    def test_singleton_reference_sees_update(self) -> None:
        """模拟 `from src.config import settings` 的消费方：字段变更必须立即可见"""
        from src.config.settings import settings as singleton

        snapshot = deepcopy(singleton)
        try:
            source = Settings()
            source.metrics.mtld_threshold = 0.9
            apply_settings_onto(singleton, source)
            assert singleton.metrics.mtld_threshold == 0.9
        finally:
            apply_settings_onto(singleton, snapshot)


class TestEnvFile:
    def test_update_preserves_comments_and_order(self, tmp_path: Path) -> None:
        env_path = tmp_path / ".env"
        env_path.write_text(
            "# 数据库\nDATABASE_URL=postgresql://x\n\n# 模型\nMODEL_BASE_URL=http://old/v1\nMODEL_ID=old-model\n",
            encoding="utf-8",
        )

        update_env_file(env_path, {"MODEL_BASE_URL": "http://new/v1"})

        lines = env_path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "# 数据库"
        assert lines[3] == "# 模型"
        assert "MODEL_BASE_URL=http://new/v1" in lines
        assert "MODEL_ID=old-model" in lines
        assert "DATABASE_URL=postgresql://x" in lines

    def test_delete_key_with_none(self, tmp_path: Path) -> None:
        env_path = tmp_path / ".env"
        env_path.write_text("MODEL_KEY=secret\nMODEL_ID=m\n", encoding="utf-8")

        update_env_file(env_path, {"MODEL_KEY": None})

        content = env_path.read_text(encoding="utf-8")
        assert "MODEL_KEY" not in content
        assert "MODEL_ID=m" in content

    def test_appends_missing_keys(self, tmp_path: Path) -> None:
        env_path = tmp_path / ".env"
        env_path.write_text("# 头注释\n", encoding="utf-8")

        update_env_file(env_path, {"LTP_MODEL_DIR": "/models/ltp"})

        lines = env_path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "# 头注释"
        assert lines[-1] == "LTP_MODEL_DIR=/models/ltp"

    def test_rejects_non_whitelisted_keys(self, tmp_path: Path) -> None:
        with pytest.raises(EnvFileError, match="白名单"):
            update_env_file(tmp_path / ".env", {"DATABASE_PASSWORD": "x"})
        with pytest.raises(EnvFileError, match="白名单"):
            apply_env_updates_to_process({"DATABASE_URL": "x"})

    def test_whitelist_covers_seven_model_keys(self) -> None:
        assert MODEL_ENV_KEYS == {
            "MODEL_BASE_URL",
            "MODEL_ID",
            "MODEL_KEY",
            "EMBEDDING_MODEL_BASE_URL",
            "EMBEDDING_MODEL_ID",
            "EMBEDDING_MODEL_KEY",
            "LTP_MODEL_DIR",
        }

    def test_apply_updates_process_environ(self, monkeypatch) -> None:
        monkeypatch.delenv("MODEL_KEY", raising=False)
        apply_env_updates_to_process({"MODEL_KEY": " new-key "})
        assert os.environ["MODEL_KEY"] == " new-key "
        monkeypatch.delenv("MODEL_KEY", raising=False)
        apply_env_updates_to_process({"MODEL_KEY": None})
        assert "MODEL_KEY" not in os.environ
