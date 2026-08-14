"""
Token 计数工具测试

覆盖 src/utils/token_counter.py：
- 编码器选择（精确/前缀/默认）
- count_tokens 正常与异常回退路径

2026-08-12 创建，补齐该模块 38% 的低覆盖率（mock tiktoken 保证离线可跑）。
2026-08-13 P2-5 移除 count_messages_tokens/estimate_completion_tokens/format_token_count
（无调用方死代码）后，同步删除对应测试。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.utils.token_counter import (
    DEFAULT_ENCODING,
    _encoding_cache,
    _get_encoding,
    _get_encoding_for_model,
    count_tokens,
)


def _fake_encoding() -> MagicMock:
    encoding = MagicMock()
    encoding.encode.return_value = ["a", "b", "c"]  # 3 tokens
    return encoding


def teardown_function() -> None:
    _encoding_cache.clear()


# ============================================================================
# 编码器选择
# ============================================================================


def test_get_encoding_for_model_exact_match() -> None:
    assert _get_encoding_for_model("gpt-4") == "cl100k_base"
    assert _get_encoding_for_model("GPT-4O-MINI") == "o200k_base"  # 大小写不敏感


def test_get_encoding_for_model_prefix_match() -> None:
    assert _get_encoding_for_model("gpt-4o-2024-05-13") == "o200k_base"


def test_get_encoding_for_model_default() -> None:
    assert _get_encoding_for_model("unknown-model") == DEFAULT_ENCODING


def test_get_encoding_caches_instances() -> None:
    with patch("src.utils.token_counter.tiktoken.get_encoding", return_value=_fake_encoding()) as mock_get:
        enc1 = _get_encoding("cl100k_base")
        enc2 = _get_encoding("cl100k_base")
        assert enc1 is enc2
        mock_get.assert_called_once_with("cl100k_base")


# ============================================================================
# count_tokens
# ============================================================================


def test_count_tokens_empty_text() -> None:
    assert count_tokens("") == 0
    assert count_tokens(None) == 0  # type: ignore[arg-type]


def test_count_tokens_uses_model_encoding() -> None:
    with patch("src.utils.token_counter.tiktoken.get_encoding", return_value=_fake_encoding()):
        assert count_tokens("你好，世界！", model="gpt-4") == 3


def test_count_tokens_falls_back_on_error() -> None:
    with patch("src.utils.token_counter.tiktoken.get_encoding", side_effect=RuntimeError("no network")):
        # 回退估算：ASCII 每字符 1 token
        assert count_tokens("abc", model="gpt-4") == 3
        # 中文每字符 2 token
        assert count_tokens("你好", model="gpt-4") == 4
