"""
指标文本工具兼容导出。

修改时间: 2026-04-23
任务: P2-基础设施解耦
修改内容: 真实实现上移到 src.utils.text_utils，保留本模块导出以兼容既有 metrics 调用与测试 patch 路径。
"""

from __future__ import annotations

from src.utils.text_utils import dialogue_length, split_sentences, tokenize_words

__all__ = ["dialogue_length", "split_sentences", "tokenize_words"]
