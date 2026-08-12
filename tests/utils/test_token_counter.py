"""
Token 计数工具测试

覆盖 src/utils/token_counter.py：
- 编码器选择（精确/前缀/默认）
- count_tokens / count_messages_tokens 正常与异常回退路径
- 估算与格式化

2026-08-12 创建，补齐该模块 38% 的低覆盖率（mock tiktoken 保证离线可跑）。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.utils.token_counter import (
    DEFAULT_ENCODING,
    _encoding_cache,
    _get_encoding,
    _get_encoding_for_model,
    count_messages_tokens,
    count_tokens,
    estimate_completion_tokens,
    format_token_count,
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


# ============================================================================
# count_messages_tokens
# ============================================================================


def test_count_messages_tokens_empty() -> None:
    assert count_messages_tokens([]) == 0


def test_count_messages_tokens_accounting() -> None:
    with patch("src.utils.token_counter.tiktoken.get_encoding", return_value=_fake_encoding()) as mock_get:
        # 每条消息 4 + role(3) + content(3)，最后 +2
        assert count_messages_tokens([{"role": "user", "content": "hi"}]) == 4 + 3 + 3 + 2
        two_messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}]
        assert count_messages_tokens(two_messages) == 2 * (4 + 3 + 3) + 2
        mock_get.assert_called()


def test_count_messages_tokens_missing_fields() -> None:
    with patch("src.utils.token_counter.tiktoken.get_encoding", return_value=_fake_encoding()):
        # 缺 role/content 时只计基础 4 token
        assert count_messages_tokens([{}]) == 4 + 2


def test_count_messages_tokens_falls_back_on_error() -> None:
    with patch("src.utils.token_counter.tiktoken.get_encoding", side_effect=RuntimeError("boom")):
        assert count_messages_tokens([{"role": "user", "content": "x"}, {"role": "user", "content": "y"}]) == 200


# ============================================================================
# 估算与格式化
# ============================================================================


def test_estimate_completion_tokens() -> None:
    assert estimate_completion_tokens(100) == 150
    assert estimate_completion_tokens(100, ratio=2.0) == 200


def test_format_token_count() -> None:
    assert format_token_count(999) == "999"
    assert format_token_count(1_500) == "1.5K"
    assert format_token_count(2_000_000) == "2.00M"
