"""
模型交互记录存储模块

创建时间: 2026-03-19
创建者: TraeAI
任务: 统一模型交互记录存储逻辑
说明: 提供统一的模型交互记录保存功能，支持传入session或使用独立session

修改记录:
- 2026-03-19 TraeAI 初始创建
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.models.annotation import AnnotationClient
    from src.models.disambiguation import DisambiguationClient


def save_annotation_interaction(
    client: AnnotationClient,
    run_id: str | None,
    chunk_id: int | None,
    phase: str,
    attempt_number: int,
    messages: list[dict],
    content_clean: str,
    thinking_content: str | None,
    duration_ms: int,
    is_cloud: bool,
    session: Session | None = None,
) -> None:
    """
    保存标注阶段的模型交互记录

    Args:
        client: 标注客户端
        run_id: 运行ID
        chunk_id: Chunk ID
        phase: 阶段名称
        attempt_number: 尝试次数
        messages: 消息列表
        content_clean: 响应内容
        thinking_content: 思考内容
        duration_ms: 耗时（毫秒）
        is_cloud: 是否云端模型
        session: 可选的数据库session，如果传入则使用传入的session，否则创建新session
    """
    if not run_id:
        return

    try:
        from src.storage.repositories.model_interaction_repository import ModelInteractionRepository

        prompt_text = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

        # 如果传入了session，使用传入的session
        if session is not None:
            repo = ModelInteractionRepository(session)
            repo.save_interaction(
                run_id=run_id,
                chunk_id=chunk_id,
                interaction_type="annotate",
                phase=phase,
                attempt_number=attempt_number,
                model_name=client._config.model if hasattr(client._config, 'model') else None,
                model_provider="cloud" if is_cloud else "local",
                prompt=prompt_text,
                response=content_clean,
                thinking=thinking_content,
                response_chars=len(content_clean),
                thinking_chars=len(thinking_content) if thinking_content else 0,
                has_thinking=bool(thinking_content and thinking_content.strip()),
                status="success",
                duration_ms=duration_ms,
            )
        else:
            # 没有传入session，创建新session
            from src.storage.db import get_session_factory
            Session = get_session_factory()
            new_session = Session()
            try:
                repo = ModelInteractionRepository(new_session)
                repo.save_interaction(
                    run_id=run_id,
                    chunk_id=chunk_id,
                    interaction_type="annotate",
                    phase=phase,
                    attempt_number=attempt_number,
                    model_name=client._config.model if hasattr(client._config, 'model') else None,
                    model_provider="cloud" if is_cloud else "local",
                    prompt=prompt_text,
                    response=content_clean,
                    thinking=thinking_content,
                    response_chars=len(content_clean),
                    thinking_chars=len(thinking_content) if thinking_content else 0,
                    has_thinking=bool(thinking_content and thinking_content.strip()),
                    status="success",
                    duration_ms=duration_ms,
                )
            finally:
                new_session.close()
    except Exception as e:
        logger.warning(f"Failed to save annotation interaction: {e}")


def save_disambiguation_interaction(
    client: DisambiguationClient | Any,
    run_id: str | None,
    candidates: list,
    context_sentences: dict,
    result: Any,
    stage_name: str,
    attempt_number: int,
    duration_ms: int,
    session: Session | None = None,
) -> None:
    """
    保存消歧阶段的模型交互记录

    Args:
        client: 消歧客户端
        run_id: 运行ID
        candidates: 候选列表
        context_sentences: 上下文句子
        result: 消歧结果
        stage_name: 阶段名称
        attempt_number: 尝试次数
        duration_ms: 耗时（毫秒）
        session: 可选的数据库session，如果传入则使用传入的session，否则创建新session
    """
    if not run_id:
        return

    try:
        import json

        from src.models.local.disambiguation import build_disambiguate_messages
        from src.storage.repositories.model_interaction_repository import ModelInteractionRepository

        messages = build_disambiguate_messages(candidates, context_sentences, None, None)
        prompt_text = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

        # 构建响应内容
        if hasattr(result, 'merge_target_map'):
            # ExtendedDisambigResult
            response_dict = {
                "merge_target_map": result.merge_target_map,
                "common_name_map": result.common_name_map if hasattr(result, 'common_name_map') else {},
                "entity_types": result.entity_types if hasattr(result, 'entity_types') else {},
                "entity_relations": result.entity_relations if hasattr(result, 'entity_relations') else [],
            }
        elif isinstance(result, dict):
            response_dict = {"merge_target_map": result, "common_name_map": {}, "entity_types": {}, "entity_relations": []}
        else:
            response_dict = {"merge_target_map": {}, "common_name_map": {}, "entity_types": {}, "entity_relations": []}
        response_text = json.dumps(response_dict, ensure_ascii=False)

        is_cloud = client.is_cloud_api() if hasattr(client, 'is_cloud_api') else False

        # 如果传入了session，使用传入的session
        if session is not None:
            repo = ModelInteractionRepository(session)
            repo.save_interaction(
                run_id=run_id,
                chunk_id=None,  # 消歧阶段没有特定 chunk_id
                interaction_type="disambiguate",
                phase=stage_name.replace(" ", "_"),
                attempt_number=attempt_number,
                model_name=client._config.model if hasattr(client, '_config') else None,
                model_provider="cloud" if is_cloud else "local",
                prompt=prompt_text,
                response=response_text,
                thinking=None,
                response_chars=len(response_text),
                thinking_chars=0,
                has_thinking=False,
                status="success",
                duration_ms=duration_ms,
            )
        else:
            # 没有传入session，创建新session
            from src.storage.db import get_session_factory
            Session = get_session_factory()
            new_session = Session()
            try:
                repo = ModelInteractionRepository(new_session)
                repo.save_interaction(
                    run_id=run_id,
                    chunk_id=None,
                    interaction_type="disambiguate",
                    phase=stage_name.replace(" ", "_"),
                    attempt_number=attempt_number,
                    model_name=client._config.model if hasattr(client, '_config') else None,
                    model_provider="cloud" if is_cloud else "local",
                    prompt=prompt_text,
                    response=response_text,
                    thinking=None,
                    response_chars=len(response_text),
                    thinking_chars=0,
                    has_thinking=False,
                    status="success",
                    duration_ms=duration_ms,
                )
            finally:
                new_session.close()
    except Exception as e:
        logger.warning(f"Failed to save disambiguation interaction: {e}")
