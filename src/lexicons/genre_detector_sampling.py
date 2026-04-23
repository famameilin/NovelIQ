"""
类型检测采样与文件读取辅助。

创建时间: 2026-04-23
任务: p1-genre-detector-split
说明: 拆出文件采样、分段切片和 weighted 采样索引计算逻辑。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def read_text_with_fallback(file_path: Path, limit: int | None = None) -> str | None:
    """
    用多编码兜底读取文本。

    创建时间: 2026-04-23
    任务: p1-genre-detector-split
    说明: 统一处理 genre detect 的文件读取分支，避免多个入口重复维护编码兜底。
    """
    encodings = ["utf-8", "gbk", "gb2312"]
    for encoding in encodings:
        try:
            with open(file_path, encoding=encoding) as file:
                return file.read(limit) if limit is not None else file.read()
        except UnicodeDecodeError:
            continue
    return None


def build_text_segments(
    text: str,
    segment_size: int,
    overlap: int,
) -> list[tuple[int, int, str]]:
    """
    构建分段检测的文本窗口。

    创建时间: 2026-04-23
    任务: p1-genre-detector-split
    说明: 把分段切片逻辑单独抽出，便于 sequence detect 复用与测试。
    """
    segments: list[tuple[int, int, str]] = []
    text_len = len(text)
    start = 0
    while start < text_len:
        end = min(start + segment_size, text_len)
        segments.append((start, end, text[start:end]))
        start = end - overlap if end < text_len else text_len
    return segments


def sample_weighted_chunk_indices(
    total_chunks: int,
    sample_ratio: float,
    min_samples: int,
) -> list[int]:
    """
    计算 weighted detect 的均匀采样索引。

    创建时间: 2026-04-23
    任务: p1-genre-detector-split
    说明: 将 weighted 采样策略单独抽出，降低 detect 主函数的流程复杂度。
    """
    if total_chunks <= 0:
        return []
    target_samples = int(total_chunks * sample_ratio)
    sample_count = max(min_samples, min(target_samples, total_chunks))
    step = max(1, total_chunks // sample_count)
    return list(range(0, total_chunks, step))[:sample_count]
