"""
创建时间: 2026-03-19
创建者: TraeAI
任务: 模型交互记录 Repository
说明: 提供模型交互记录的增删改查操作
"""

from datetime import datetime
from typing import Any

from sqlalchemy import desc, select

from src.storage.models import ModelInteraction
from src.storage.repositories.base import BaseRepository


class ModelInteractionRepository(BaseRepository):
    """
    模型交互记录 Repository

    创建时间: 2026-03-19
    创建者: TraeAI
    任务: 保存模型交互记录
    """

    def save_interaction(
        self,
        run_id: str,
        chunk_id: int | None,
        interaction_type: str,
        phase: str | None,
        attempt_number: int,
        model_name: str | None,
        model_provider: str | None,
        prompt: str,
        response: str,
        thinking: str | None = None,
        response_chars: int | None = None,
        thinking_chars: int | None = None,
        has_thinking: bool = False,
        status: str = "success",
        error_message: str | None = None,
        duration_ms: int | None = None,
    ) -> ModelInteraction:
        """
        保存模型交互记录

        Args:
            run_id: 运行ID
            chunk_id: 分块ID（可选，diagnose阶段可能为None）
            interaction_type: 交互类型（annotate/diagnose/disambiguate）
            phase: 阶段（phase1/phase2/cloud_fallback）
            attempt_number: 尝试次数
            model_name: 模型名称
            model_provider: 模型提供者（local/cloud）
            prompt: 提示词
            response: 响应内容
            thinking: 思考内容
            response_chars: 响应字符数
            thinking_chars: 思考字符数
            has_thinking: 是否有思考内容
            status: 状态（success/error）
            error_message: 错误信息
            duration_ms: 调用耗时（毫秒）

        Returns:
            保存的 ModelInteraction 对象
        """
        interaction = ModelInteraction(
            run_id=run_id,
            chunk_id=chunk_id,
            interaction_type=interaction_type,
            phase=phase,
            attempt_number=attempt_number,
            model_name=model_name,
            model_provider=model_provider,
            prompt=prompt,
            response=response,
            thinking=thinking,
            response_chars=response_chars or len(response),
            thinking_chars=thinking_chars or (len(thinking) if thinking else 0),
            has_thinking=1 if has_thinking else 0,
            status=status,
            error_message=error_message,
            duration_ms=duration_ms,
            created_at=datetime.utcnow(),
        )
        self.session.add(interaction)
        self.session.commit()
        return interaction

    def get_interactions_by_chunk(
        self,
        run_id: str,
        chunk_id: int,
        interaction_type: str | None = None,
    ) -> list[ModelInteraction]:
        """
        获取指定 chunk 的所有交互记录

        Args:
            run_id: 运行ID
            chunk_id: 分块ID
            interaction_type: 交互类型过滤（可选）

        Returns:
            交互记录列表
        """
        stmt = select(ModelInteraction).where(
            ModelInteraction.run_id == run_id,
            ModelInteraction.chunk_id == chunk_id,
        )
        if interaction_type:
            stmt = stmt.where(ModelInteraction.interaction_type == interaction_type)
        stmt = stmt.order_by(ModelInteraction.created_at)
        return list(self.session.execute(stmt).scalars().all())

    def get_interactions_by_run(
        self,
        run_id: str,
        interaction_type: str | None = None,
    ) -> list[ModelInteraction]:
        """
        获取指定 run 的所有交互记录

        Args:
            run_id: 运行ID
            interaction_type: 交互类型过滤（可选）

        Returns:
            交互记录列表
        """
        stmt = select(ModelInteraction).where(
            ModelInteraction.run_id == run_id,
        )
        if interaction_type:
            stmt = stmt.where(ModelInteraction.interaction_type == interaction_type)
        stmt = stmt.order_by(desc(ModelInteraction.created_at))
        return list(self.session.execute(stmt).scalars().all())

    def get_latest_interaction(
        self,
        run_id: str,
        chunk_id: int,
        interaction_type: str,
    ) -> ModelInteraction | None:
        """
        获取指定 chunk 的最新交互记录

        Args:
            run_id: 运行ID
            chunk_id: 分块ID
            interaction_type: 交互类型

        Returns:
            最新的交互记录，如果没有则返回 None
        """
        stmt = (
            select(ModelInteraction)
            .where(
                ModelInteraction.run_id == run_id,
                ModelInteraction.chunk_id == chunk_id,
                ModelInteraction.interaction_type == interaction_type,
            )
            .order_by(desc(ModelInteraction.created_at))
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_interaction_stats(
        self,
        run_id: str,
    ) -> dict[str, Any]:
        """
        获取交互统计信息

        Args:
            run_id: 运行ID

        Returns:
            统计信息字典
        """
        stmt = select(ModelInteraction).where(ModelInteraction.run_id == run_id)
        interactions = list(self.session.execute(stmt).scalars().all())

        total_count = len(interactions)
        success_count = sum(1 for i in interactions if i.status == "success")
        error_count = sum(1 for i in interactions if i.status == "error")

        type_stats: dict[str, int] = {}
        for i in interactions:
            type_stats[i.interaction_type] = type_stats.get(i.interaction_type, 0) + 1

        return {
            "total_count": total_count,
            "success_count": success_count,
            "error_count": error_count,
            "type_stats": type_stats,
        }
