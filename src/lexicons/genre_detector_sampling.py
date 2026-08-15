"""
类型检测采样与文件读取辅助

拆出文件采样、分段切片和 weighted 采样索引计算逻辑

2026-08-14 新增段落级分层抽样（设计《章节粒度分析指标重设计》§11.2）：
按归一化字符位置把全文分成固定层数，每层确定性选段，
支持 token 预算截断，短篇返回全部段落。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def read_text_with_fallback(file_path: Path, limit: int | None = None) -> str | None:
    """
    用多编码兜底读取文本

    统一处理 genre detect 的文件读取分支，避免多个入口重复维护编码兜底
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
    构建分段检测的文本窗口

    把分段切片逻辑单独抽出，便于 sequence detect 复用与测试
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
    total_chapters: int,
    sample_ratio: float,
    min_samples: int,
) -> list[int]:
    """
    计算 weighted detect 的均匀采样索引

    将 weighted 采样策略单独抽出，降低 detect 主函数的流程复杂度
    """
    if total_chapters <= 0:
        return []
    target_samples = int(total_chapters * sample_ratio)
    sample_count = max(min_samples, min(target_samples, total_chapters))
    step = max(1, total_chapters // sample_count)
    return list(range(0, total_chapters, step))[:sample_count]


@dataclass(frozen=True)
class ParagraphSamplingResult:
    """段落分层抽样结果（设计 §11.2），保证可审计"""

    paragraph_ids: list[int]
    coverage_char_ratio: float  # 抽样段落字符数 / 总字符数
    coverage_token_ratio: float  # 抽样段落 token 数 / 总 token 数
    layer_count: int


def sample_paragraphs_by_char_position(
    paragraphs: Sequence[tuple[int, int, int, int, int]],
    # (paragraph_id, global_start_char, global_end_char, char_count, token_count)，
    # 按 global_start_char 升序
    sample_ratio: float = 0.1,
    min_samples: int = 10,
    token_budget: int | None = None,
) -> ParagraphSamplingResult:
    """
    按归一化字符位置分层抽样段落（设计 §11.2）

    全文按字符位置分成固定层数 layer_count，每层区间按全文字符长度均分；
    每层在 global_start 落在区间内的段落中，确定性选取字符中点最接近层中点的段落
    （层内无段落则跳过）；token_budget 给定且累计 token 超过预算时停止后续层；
    短篇（total <= min_samples）返回全部段落。

    Args:
        paragraphs: (paragraph_id, global_start_char, global_end_char, char_count,
            token_count) 元组序列，须按 global_start_char 升序且坐标单调不重叠
        sample_ratio: 目标抽样比例
        min_samples: 最少层数（也即最少抽样段落数）
        token_budget: 抽样 token 预算，超过后停止后续层

    Returns:
        ParagraphSamplingResult：段落 ID 按原文顺序、字符/token 覆盖比例、层数
    """
    total = len(paragraphs)
    if total == 0:
        return ParagraphSamplingResult(
            paragraph_ids=[],
            coverage_char_ratio=0.0,
            coverage_token_ratio=0.0,
            layer_count=0,
        )

    total_chars = sum(char_count for *_, char_count, _ in paragraphs)
    total_tokens = sum(token_count for *_, token_count in paragraphs)

    # 短篇：返回全部段落（§11.2 短篇用全部段落）
    if total <= min_samples:
        return ParagraphSamplingResult(
            paragraph_ids=[paragraph[0] for paragraph in paragraphs],
            coverage_char_ratio=1.0,
            coverage_token_ratio=1.0 if total_tokens > 0 else 0.0,
            layer_count=max(min_samples, min(int(total * sample_ratio), total)),
        )

    layer_count = max(min_samples, min(int(total * sample_ratio), total))
    # 全文字符长度：段落坐标单调不重叠，末段 global_end 即全文长度
    full_len = paragraphs[-1][2]

    selected_ids: list[int] = []
    cumulative_tokens = 0
    for layer_index in range(layer_count):
        # 累计 token 超过预算时停止后续层
        if token_budget is not None and cumulative_tokens > token_budget:
            break
        layer_start = full_len * layer_index / layer_count
        layer_end = full_len * (layer_index + 1) / layer_count
        layer_mid = (layer_start + layer_end) / 2

        # 层内确定性选段：global_start 落在区间内，字符中点最接近层中点
        best: tuple[int, int, int, int, int] | None = None
        best_distance = float("inf")
        for paragraph in paragraphs:
            paragraph_id, global_start, global_end, char_count, token_count = paragraph
            if layer_start <= global_start < layer_end:
                midpoint = (global_start + global_end) / 2
                distance = abs(midpoint - layer_mid)
                if distance < best_distance:
                    best_distance = distance
                    best = paragraph
        if best is None:
            # 层内无段落，跳过该层
            continue
        selected_ids.append(best[0])
        cumulative_tokens += best[4]

    selected_chars = sum(
        char_count
        for paragraph_id, _, _, char_count, _ in paragraphs
        if paragraph_id in selected_ids
    )
    selected_tokens = sum(
        token_count
        for paragraph_id, _, _, _, token_count in paragraphs
        if paragraph_id in selected_ids
    )

    return ParagraphSamplingResult(
        paragraph_ids=selected_ids,
        coverage_char_ratio=selected_chars / total_chars if total_chars > 0 else 0.0,
        coverage_token_ratio=selected_tokens / total_tokens if total_tokens > 0 else 0.0,
        layer_count=layer_count,
    )

