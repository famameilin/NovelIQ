"""2026-09-10 设置注册表与 settings 热生效工具的闸门测试

覆盖：
- diff_user_overrides 稀疏化（含开放键空间 dict 例外）
- apply_settings_onto 原地热生效（单例身份不变）
- env_file 白名单编辑器（保注释保序 / 删除 / 追加 / 白名单违规）
"""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path

import pytest

from src.config.env_file import EnvFileError, apply_env_updates_to_process, update_env_file
from src.config.settings import (
    Settings,
    apply_settings_onto,
    diff_user_overrides,
)


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
        with pytest.raises(EnvFileError):
            update_env_file(tmp_path / ".env", {"DATABASE_PASSWORD": "x"})
        with pytest.raises(EnvFileError):
            apply_env_updates_to_process({"DATABASE_URL": "x"})

    def test_apply_updates_process_environ(self, monkeypatch) -> None:
        monkeypatch.delenv("MODEL_KEY", raising=False)
        apply_env_updates_to_process({"MODEL_KEY": " new-key "})
        assert os.environ["MODEL_KEY"] == " new-key "
        monkeypatch.delenv("MODEL_KEY", raising=False)
        apply_env_updates_to_process({"MODEL_KEY": None})
        assert "MODEL_KEY" not in os.environ
