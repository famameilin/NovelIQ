from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.storage.repositories import ChapterRepository


def get_prev_tail_text(
    chunk_repo: ChapterRepository,
    run_id: str,
    chunk_id: int,
    tail_chars: int = 200,
) -> str | None:
    """
    获取上一个 chunk 的完整文本
    """
    return chunk_repo.fetch_prev_chapter_text(run_id, chunk_id)


def get_next_text(
    chunk_repo: ChapterRepository,
    run_id: str,
    chunk_id: int,
) -> str | None:
    """
    获取下一个 chunk 的完整文本
    """
    return chunk_repo.fetch_next_chapter_text(run_id, chunk_id)


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
