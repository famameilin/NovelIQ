from __future__ import annotations

from typing import TYPE_CHECKING

"""
创建时间: 2025-03-12
创建者: TraeAI
任务: 滚动记忆管理

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 返回完整的上一个 chunk 文本，而不是只返回末尾部分

修改时间: 2026-03-14
修改者: TraeAI
任务: metrics-repository-refactor
修改内容: 重构为使用 Repository 模式
- 通过 ChunkRepository 查询
- 添加 run_id 参数支持
"""

if TYPE_CHECKING:
    from src.storage.repositories import ChunkRepository


def get_prev_tail_text(
    chunk_repo: "ChunkRepository",
    run_id: str,
    chunk_id: int,
    tail_chars: int = 200,
) -> str | None:
    """
    获取上一个 chunk 的完整文本

    修改时间: 2026-03-12
    修改者: TraeAI
    修改内容: 返回完整的上一个 chunk 文本，而不是只返回末尾部分

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 ChunkRepository 接口，添加 run_id 参数
    """
    return chunk_repo.fetch_prev_chunk_text(run_id, chunk_id)


def get_next_text(
    chunk_repo: "ChunkRepository",
    run_id: str,
    chunk_id: int,
) -> str | None:
    """
    获取下一个 chunk 的完整文本

    创建时间: 2026-03-12
    创建者: TraeAI
    任务: 优化上下文传递，新增 Next_Context

    修改时间: 2026-03-14
    修改者: TraeAI
    任务: metrics-repository-refactor
    修改内容: 使用 ChunkRepository 接口，添加 run_id 参数
    """
    return chunk_repo.fetch_next_chunk_text(run_id, chunk_id)


def format_rolling_memory_for_prompt(
    prev_tail_text: str | None,
    active_entities: str | None,
) -> str:
    parts = []
    if prev_tail_text:
        parts.append(f"<Previous_Context>\n{prev_tail_text}\n</Previous_Context>")
    if active_entities:
        parts.append(f"<Active_Entities>\n{active_entities}\n</Active_Entities>")
    if not parts:
        return ""
    return "\n\n".join(parts)
