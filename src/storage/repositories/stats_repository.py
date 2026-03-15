"""
创建时间: 2026-03-14
创建者: TraeAI
任务: 实现 StatsRepository 类
说明: 统计数据的数据库操作实现，支持 run_id 参数

修改时间: 2026-03-14
修改者: TraeAI
任务: refactor-routes-use-repository
修改内容: 添加查询方法 fetch_emotion_curve, fetch_rhythm_curve, fetch_cloud_analysis, fetch_global_stats_dict

修改时间: 2026-03-15
修改者: TraeAI
任务: postgresql-migration
修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session，使用 ORM 查询替代原生 SQL
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.models.cloud.schema import CloudAnalysis as CloudAnalysisSchema
from src.storage.models import (
    Chunk,
    ChunkCulture,
    ChunkSummary,
    ChunkTopic,
    CloudAnalysis,
    EmotionCurve,
    GlobalContext,
    GlobalStats,
    GraphStorage,
    RhythmCurve,
    TokenUsage,
    CharacterAppearance,
)

from .base import BaseRepository


class StatsRepository(BaseRepository[Dict[str, Any]]):
    """
    统计数据 Repository

    管理全局统计、情绪曲线、节奏曲线、云端分析等数据。
    所有方法支持 run_id 参数以区分不同的分析运行。

    修改时间: 2026-03-15
    修改者: TraeAI
    任务: postgresql-migration
    修改内容: 从 sqlite3.Connection 迁移到 SQLAlchemy Session
    """

    def insert_global_stats(self, run_id: str, stats: Iterable[Tuple[str, float]]) -> None:
        """
        插入全局统计数据

        Args:
            run_id: 运行ID
            stats: 统计数据迭代器 (stat_name, stat_value)
        """
        stats_list = list(stats)
        if not stats_list:
            return

        for stat_name, stat_value in stats_list:
            stmt = pg_insert(GlobalStats).values(
                stat_name=stat_name,
                stat_value=stat_value,
                run_id=run_id,
            ).on_conflict_do_update(
                index_elements=["stat_name"],
                set_={
                    "stat_value": stat_value,
                    "run_id": run_id,
                },
            )
            self.session.execute(stmt)
        self.session.commit()

    def fetch_global_stats(self, run_id: str) -> List[Tuple[str, float]]:
        """
        获取全局统计数据

        Args:
            run_id: 运行ID

        Returns:
            (stat_name, stat_value) 元组列表
        """
        stmt = select(GlobalStats.stat_name, GlobalStats.stat_value).where(
            GlobalStats.run_id == run_id
        )
        result = self.session.execute(stmt)
        return [(row.stat_name, row.stat_value) for row in result.fetchall()]

    def insert_emotion_curve(
        self, run_id: str, rows: Iterable[Tuple[int, float, float, float, float]]
    ) -> None:
        """
        插入情绪曲线数据

        Args:
            run_id: 运行ID
            rows: 情绪数据迭代器 (chunk_id, pos_density, neg_density, net_density, smoothed_density)
        """
        data_list = list(rows)
        if not data_list:
            return

        for chunk_id, pos_density, neg_density, net_density, smoothed_density in data_list:
            stmt = pg_insert(EmotionCurve).values(
                chunk_id=chunk_id,
                pos_density=pos_density,
                neg_density=neg_density,
                net_density=net_density,
                smoothed_density=smoothed_density,
                run_id=run_id,
            ).on_conflict_do_update(
                index_elements=["chunk_id"],
                set_={
                    "pos_density": pos_density,
                    "neg_density": neg_density,
                    "net_density": net_density,
                    "smoothed_density": smoothed_density,
                    "run_id": run_id,
                },
            )
            self.session.execute(stmt)
        self.session.commit()

    def insert_rhythm_curve(self, run_id: str, rows: Iterable[Tuple[int, float, float]]) -> None:
        """
        插入节奏曲线数据

        Args:
            run_id: 运行ID
            rows: 节奏数据迭代器 (chunk_id, tension_proxy, tension_composite)
        """
        data_list = list(rows)
        if not data_list:
            return

        for chunk_id, tension_proxy, tension_composite in data_list:
            stmt = pg_insert(RhythmCurve).values(
                chunk_id=chunk_id,
                tension_proxy=tension_proxy,
                tension_composite=tension_composite,
                run_id=run_id,
            ).on_conflict_do_update(
                index_elements=["chunk_id"],
                set_={
                    "tension_proxy": tension_proxy,
                    "tension_composite": tension_composite,
                    "run_id": run_id,
                },
            )
            self.session.execute(stmt)
        self.session.commit()

    def insert_cloud_analysis(self, run_id: str, analysis: CloudAnalysisSchema) -> None:
        """
        插入云端分析结果

        Args:
            run_id: 运行ID
            analysis: 云端分析数据
        """
        arc_scores_json: str
        if isinstance(analysis.arc_scores, dict):
            arc_scores_json = json.dumps(analysis.arc_scores, ensure_ascii=False)
        else:
            arc_scores_json = json.dumps(list(analysis.arc_scores), ensure_ascii=False)

        cloud_analysis = CloudAnalysis(
            novel_id=analysis.novel_id,
            foreshadow_rate=analysis.foreshadow_rate,
            arc_scores=arc_scores_json,
            narrative_type=analysis.narrative_type,
            topic_labels=json.dumps(list(analysis.topic_labels), ensure_ascii=False),
            diagnosis=analysis.diagnosis,
            value_logic_type=analysis.value_logic_type,
            value_logic_reason=analysis.value_logic_reason,
            power_stance_score=analysis.power_stance_score,
            power_stance_reason=analysis.power_stance_reason,
            common_people_dignity=analysis.common_people_dignity,
            dignity_reason=analysis.dignity_reason,
            cultural_depth_score=analysis.cultural_depth_score,
            cultural_depth_reason=analysis.cultural_depth_reason,
            emotion_curve_type=analysis.emotion_curve_type,
            run_id=run_id,
        )
        self.session.add(cloud_analysis)
        self.session.commit()

    def insert_global_context(
        self,
        run_id: str,
        novel_id: str,
        core_characters: str,
        world_setting: str,
        novel_title: str | None = None,
    ) -> None:
        """
        插入全局上下文

        Args:
            run_id: 运行ID
            novel_id: 小说ID
            core_characters: 核心角色
            world_setting: 世界观设定
            novel_title: 小说标题（可选）
        """
        now = datetime.now().isoformat()
        stmt = pg_insert(GlobalContext).values(
            novel_id=novel_id,
            novel_title=novel_title,
            core_characters=core_characters,
            world_setting=world_setting,
            updated_at=now,
            run_id=run_id,
        ).on_conflict_do_update(
            index_elements=["novel_id"],
            set_={
                "novel_title": novel_title,
                "core_characters": core_characters,
                "world_setting": world_setting,
                "updated_at": now,
                "run_id": run_id,
            },
        )
        self.session.execute(stmt)
        self.session.commit()

    def fetch_global_context(
        self, run_id: str, novel_id: str
    ) -> Optional[Tuple[str, str, str, str]]:
        """
        获取全局上下文

        Args:
            run_id: 运行ID
            novel_id: 小说ID

        Returns:
            (novel_title, core_characters, world_setting, updated_at) 元组，不存在则返回 None
        """
        stmt = select(
            GlobalContext.novel_title,
            GlobalContext.core_characters,
            GlobalContext.world_setting,
            GlobalContext.updated_at,
        ).where(
            GlobalContext.novel_id == novel_id,
            GlobalContext.run_id == run_id,
        )
        result = self.session.execute(stmt).fetchone()
        if result is None:
            return None
        return (result.novel_title, result.core_characters, result.world_setting, result.updated_at)

    def update_global_context(self, run_id: str, novel_id: str, **kwargs: Any) -> None:
        """
        更新全局上下文

        Args:
            run_id: 运行ID
            novel_id: 小说ID
            **kwargs: 要更新的字段
        """
        allowed_fields = {"core_characters", "world_setting"}
        update_data = {}
        for key, value in kwargs.items():
            if key in allowed_fields:
                update_data[key] = value
        if not update_data:
            return
        update_data["updated_at"] = datetime.now().isoformat()

        stmt = (
            update(GlobalContext)
            .where(GlobalContext.novel_id == novel_id, GlobalContext.run_id == run_id)
            .values(**update_data)
        )
        self.session.execute(stmt)
        self.session.commit()

    def insert_token_usage(
        self,
        run_id: str,
        novel_id: str,
        task_type: str,
        call_type: str,
        model: str,
        prompt_tokens: int,
        total_tokens: int,
        completion_tokens: int | None = None,
        chunk_id: int | None = None,
    ) -> int | None:
        """
        插入 token 使用记录

        Args:
            run_id: 运行ID
            novel_id: 小说ID
            task_type: 任务类型
            call_type: 调用类型
            model: 模型名称
            prompt_tokens: 提示 token 数
            total_tokens: 总 token 数
            completion_tokens: 完成 token 数（可选）
            chunk_id: 分块ID（可选）

        Returns:
            插入记录的ID
        """
        now = datetime.now().isoformat()
        token_usage = TokenUsage(
            novel_id=novel_id,
            chunk_id=chunk_id,
            task_type=task_type,
            call_type=call_type,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            created_at=now,
            run_id=run_id,
        )
        self.session.add(token_usage)
        self.session.commit()
        return token_usage.id

    def fetch_token_usage_stats(self, run_id: str, novel_id: str) -> Dict[str, Any]:
        """
        获取 token 使用统计

        Args:
            run_id: 运行ID
            novel_id: 小说ID

        Returns:
            使用统计数据字典
        """
        summary = self._fetch_usage_summary(run_id, novel_id)
        by_task = self._fetch_usage_by_task(run_id, novel_id)
        by_model = self._fetch_usage_by_model(run_id, novel_id)
        return {
            "summary": summary,
            "by_task": by_task,
            "by_model": by_model,
        }

    def _fetch_usage_summary(self, run_id: str, novel_id: str) -> Dict[str, Any]:
        """获取使用量摘要"""
        stmt = select(
            func.count().label("call_count"),
            func.sum(TokenUsage.prompt_tokens).label("total_prompt_tokens"),
            func.sum(func.coalesce(TokenUsage.completion_tokens, 0)).label("total_completion_tokens"),
            func.sum(TokenUsage.total_tokens).label("total_tokens"),
        ).where(
            TokenUsage.novel_id == novel_id,
            TokenUsage.run_id == run_id,
        )
        result = self.session.execute(stmt).fetchone()
        if result is None:
            return {
                "call_count": 0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_tokens": 0,
            }
        return {
            "call_count": result.call_count or 0,
            "total_prompt_tokens": result.total_prompt_tokens or 0,
            "total_completion_tokens": result.total_completion_tokens or 0,
            "total_tokens": result.total_tokens or 0,
        }

    def _fetch_usage_by_task(self, run_id: str, novel_id: str) -> Dict[str, Any]:
        """按任务类型获取使用量"""
        stmt = select(
            TokenUsage.task_type,
            func.count().label("count"),
            func.sum(TokenUsage.total_tokens).label("total"),
        ).where(
            TokenUsage.novel_id == novel_id,
            TokenUsage.run_id == run_id,
        ).group_by(TokenUsage.task_type)

        result = self.session.execute(stmt).fetchall()
        return {row.task_type: {"call_count": row.count, "total_tokens": row.total} for row in result}

    def _fetch_usage_by_model(self, run_id: str, novel_id: str) -> Dict[str, Any]:
        """按模型获取使用量"""
        stmt = select(
            TokenUsage.model,
            func.count().label("count"),
            func.sum(TokenUsage.total_tokens).label("total"),
        ).where(
            TokenUsage.novel_id == novel_id,
            TokenUsage.run_id == run_id,
        ).group_by(TokenUsage.model)

        result = self.session.execute(stmt).fetchall()
        return {row.model: {"call_count": row.count, "total_tokens": row.total} for row in result}

    def insert_chunk_summary(self, run_id: str, chunk_id: int, summary: str) -> None:
        """
        插入 chunk 摘要

        Args:
            run_id: 运行ID
            chunk_id: 分块ID
            summary: 摘要文本
        """
        now = datetime.now().isoformat()
        stmt = pg_insert(ChunkSummary).values(
            chunk_id=chunk_id,
            summary=summary,
            created_at=now,
            run_id=run_id,
        ).on_conflict_do_update(
            index_elements=["chunk_id"],
            set_={
                "summary": summary,
                "created_at": now,
                "run_id": run_id,
            },
        )
        self.session.execute(stmt)
        self.session.commit()

    def insert_character_appearances(
        self, run_id: str, chunk_id: int, appearances: Sequence[Any]
    ) -> None:
        """
        插入角色出场信息

        Args:
            run_id: 运行ID
            chunk_id: 分块ID
            appearances: 角色出场信息序列
        """
        if not appearances:
            return
        now = datetime.now().isoformat()
        for a in appearances:
            char_appearance = CharacterAppearance(
                chunk_id=chunk_id,
                raw_name=a.raw_name,
                identity_clue=a.identity_clue,
                clue_type=a.clue_type,
                created_at=now,
                run_id=run_id,
            )
            self.session.add(char_appearance)
        self.session.commit()

    def fetch_emotion_curve(self, run_id: str) -> List[Tuple[float, float, float]]:
        """
        获取情绪曲线数据

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 aggregate_metrics.py

        Args:
            run_id: 运行ID

        Returns:
            (pos_density, neg_density, net_density) 元组列表
        """
        stmt = select(
            EmotionCurve.pos_density,
            EmotionCurve.neg_density,
            EmotionCurve.net_density,
        ).where(
            EmotionCurve.run_id == run_id
        ).order_by(EmotionCurve.chunk_id)

        result = self.session.execute(stmt).fetchall()
        return [(row.pos_density, row.neg_density, row.net_density) for row in result]

    def fetch_emotion_densities(self, run_id: str) -> List[Tuple[float, float]]:
        """
        获取情绪密度数据

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 aggregate_metrics.py

        Args:
            run_id: 运行ID

        Returns:
            (pos_density, neg_density) 元组列表
        """
        stmt = select(
            EmotionCurve.pos_density,
            EmotionCurve.neg_density,
        ).where(
            EmotionCurve.run_id == run_id
        ).order_by(EmotionCurve.chunk_id)

        result = self.session.execute(stmt).fetchall()
        return [(row.pos_density, row.neg_density) for row in result]

    def fetch_rhythm_curve(self, run_id: str) -> List[Tuple[float]]:
        """
        获取节奏曲线数据

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 aggregate_metrics.py

        Args:
            run_id: 运行ID

        Returns:
            (tension_composite,) 元组列表
        """
        stmt = select(RhythmCurve.tension_composite).where(
            RhythmCurve.run_id == run_id
        ).order_by(RhythmCurve.chunk_id)

        result = self.session.execute(stmt).fetchall()
        return [(row.tension_composite,) for row in result]

    def fetch_chunk_culture(self, run_id: str) -> List[Tuple[float, float, float, float, float, float]]:
        """
        获取分块文化数据

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 aggregate_metrics.py

        Args:
            run_id: 运行ID

        Returns:
            (confucian_density, taoist_density, buddhist_density, folk_density, allusion_density, imagery_density) 元组列表
        """
        stmt = select(
            ChunkCulture.confucian_density,
            ChunkCulture.taoist_density,
            ChunkCulture.buddhist_density,
            ChunkCulture.folk_density,
            ChunkCulture.allusion_density,
            ChunkCulture.imagery_density,
        ).where(
            ChunkCulture.run_id == run_id
        ).order_by(ChunkCulture.chunk_id)

        result = self.session.execute(stmt).fetchall()
        return [(
            row.confucian_density,
            row.taoist_density,
            row.buddhist_density,
            row.folk_density,
            row.allusion_density,
            row.imagery_density,
        ) for row in result]

    def save_graph(self, run_id: str, graph_name: str, graph_json: str) -> None:
        """
        保存图数据到数据库

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 graph.py

        Args:
            run_id: 运行ID
            graph_name: 图名称
            graph_json: 图的 JSON 序列化字符串
        """
        now = datetime.now().isoformat()
        stmt = pg_insert(GraphStorage).values(
            graph_name=graph_name,
            graph_json=graph_json,
            updated_at=now,
            run_id=run_id,
        ).on_conflict_do_update(
            constraint="uq_graph_storage_name_run",
            set_={
                "graph_json": graph_json,
                "updated_at": now,
            },
        )
        self.session.execute(stmt)
        self.session.commit()

    def load_graph(self, run_id: str, graph_name: str) -> Optional[str]:
        """
        从数据库加载图数据

        修改时间: 2026-03-14
        修改者: TraeAI
        任务: metrics-repository-refactor
        修改内容: 新增方法支持 graph.py

        Args:
            run_id: 运行ID
            graph_name: 图名称

        Returns:
            图的 JSON 序列化字符串，不存在则返回 None
        """
        stmt = select(GraphStorage.graph_json).where(
            GraphStorage.graph_name == graph_name,
            GraphStorage.run_id == run_id,
        )
        result = self.session.execute(stmt).fetchone()
        return result.graph_json if result else None

    def fetch_emotion_curve_full(self, run_id: str) -> List[Tuple[int, float, float, float, float]]:
        """
        获取情绪曲线完整数据

        Args:
            run_id: 运行ID

        Returns:
            (chunk_id, pos_density, neg_density, net_density, smoothed_density) 元组列表
        """
        stmt = select(
            EmotionCurve.chunk_id,
            EmotionCurve.pos_density,
            EmotionCurve.neg_density,
            EmotionCurve.net_density,
            EmotionCurve.smoothed_density,
        ).where(
            (EmotionCurve.run_id == run_id) | (EmotionCurve.run_id.is_(None))
        ).order_by(EmotionCurve.chunk_id)

        result = self.session.execute(stmt).fetchall()
        return [(
            row.chunk_id,
            row.pos_density,
            row.neg_density,
            row.net_density,
            row.smoothed_density,
        ) for row in result]

    def fetch_rhythm_curve_full(self, run_id: str) -> List[Tuple[int, float, float]]:
        """
        获取节奏曲线完整数据

        Args:
            run_id: 运行ID

        Returns:
            (chunk_id, tension_proxy, tension_composite) 元组列表
        """
        stmt = select(
            RhythmCurve.chunk_id,
            RhythmCurve.tension_proxy,
            RhythmCurve.tension_composite,
        ).where(
            (RhythmCurve.run_id == run_id) | (RhythmCurve.run_id.is_(None))
        ).order_by(RhythmCurve.chunk_id)

        result = self.session.execute(stmt).fetchall()
        return [(
            row.chunk_id,
            row.tension_proxy,
            row.tension_composite,
        ) for row in result]

    def fetch_cloud_analysis(self, novel_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        """
        获取云端分析结果

        Args:
            novel_id: 小说ID
            run_id: 运行ID

        Returns:
            云端分析结果字典，不存在则返回 None
        """
        stmt = select(CloudAnalysis).where(
            CloudAnalysis.novel_id == novel_id,
            (CloudAnalysis.run_id == run_id) | (CloudAnalysis.run_id.is_(None)),
        ).limit(1)

        result = self.session.execute(stmt).scalar_one_or_none()

        if result is None:
            stmt = select(CloudAnalysis).where(
                CloudAnalysis.foreshadow_rate.isnot(None),
                (CloudAnalysis.run_id == run_id) | (CloudAnalysis.run_id.is_(None)),
            ).order_by(CloudAnalysis.id.desc()).limit(1)
            result = self.session.execute(stmt).scalar_one_or_none()

        if result is None:
            return None

        return {
            "novel_id": result.novel_id,
            "foreshadow_rate": result.foreshadow_rate,
            "arc_scores": result.arc_scores,
            "narrative_type": result.narrative_type,
            "topic_labels": result.topic_labels,
            "diagnosis": result.diagnosis,
            "value_logic_type": result.value_logic_type,
            "value_logic_reason": result.value_logic_reason,
            "power_stance_score": result.power_stance_score,
            "power_stance_reason": result.power_stance_reason,
            "common_people_dignity": result.common_people_dignity,
            "dignity_reason": result.dignity_reason,
            "cultural_depth_score": result.cultural_depth_score,
            "cultural_depth_reason": result.cultural_depth_reason,
            "emotion_curve_type": result.emotion_curve_type,
            "run_id": result.run_id,
        }

    def fetch_global_stats_dict(self, run_id: str) -> Dict[str, float]:
        """
        获取全局统计数据字典

        Args:
            run_id: 运行ID

        Returns:
            统计名称到值的映射字典
        """
        stmt = select(GlobalStats.stat_name, GlobalStats.stat_value).where(
            (GlobalStats.run_id == run_id) | (GlobalStats.run_id.is_(None))
        )
        result = self.session.execute(stmt).fetchall()
        return {row.stat_name: row.stat_value for row in result}

    def fetch_novel_title(self, novel_id: str, run_id: str) -> Optional[str]:
        """
        获取小说标题

        Args:
            novel_id: 小说ID
            run_id: 运行ID

        Returns:
            小说标题，不存在则返回 None
        """
        stmt = select(GlobalContext.novel_title).where(
            GlobalContext.novel_id == novel_id,
            (GlobalContext.run_id == run_id) | (GlobalContext.run_id.is_(None)),
        ).limit(1)

        result = self.session.execute(stmt).fetchone()
        return result.novel_title if result else None

    def has_aggregated_data(self, run_id: str) -> bool:
        """
        检查指定运行是否有聚合数据

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: storage-layer-decoupling
        修改内容: 新增方法替代 operations.completeness.has_aggregated_data

        Args:
            run_id: 运行ID

        Returns:
            是否有聚合数据
        """
        emotion_count = self.session.execute(
            select(func.count()).select_from(EmotionCurve).where(EmotionCurve.run_id == run_id)
        ).scalar() or 0

        rhythm_count = self.session.execute(
            select(func.count()).select_from(RhythmCurve).where(RhythmCurve.run_id == run_id)
        ).scalar() or 0

        return emotion_count > 0 and rhythm_count > 0

    def has_topic_data(self, run_id: str) -> bool:
        """
        检查指定运行是否有主题数据

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: storage-layer-decoupling
        修改内容: 新增方法替代 operations.completeness.has_topic_data

        Args:
            run_id: 运行ID

        Returns:
            是否有主题数据
        """
        count = self.session.execute(
            select(func.count()).select_from(ChunkTopic).where(ChunkTopic.run_id == run_id)
        ).scalar() or 0
        return count > 0

    def has_diagnosis_data(self, run_id: str) -> bool:
        """
        检查指定运行是否有诊断数据

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: storage-layer-decoupling
        修改内容: 新增方法替代 operations.completeness.has_diagnosis_data

        Args:
            run_id: 运行ID

        Returns:
            是否有诊断数据
        """
        count = self.session.execute(
            select(func.count()).select_from(CloudAnalysis).where(CloudAnalysis.run_id == run_id)
        ).scalar() or 0
        return count > 0

    def is_aggregate_complete(self, run_id: str) -> bool:
        """
        检查聚合阶段是否完成

        修改时间: 2026-03-15
        修改者: TraeAI
        任务: storage-layer-decoupling
        修改内容: 新增方法替代 operations.completeness.is_aggregate_complete

        Args:
            run_id: 运行ID

        Returns:
            聚合是否完成
        """
        chunks_count = self.session.execute(
            select(func.count()).select_from(Chunk).where(Chunk.run_id == run_id)
        ).scalar() or 0

        emotion_count = self.session.execute(
            select(func.count()).select_from(EmotionCurve).where(EmotionCurve.run_id == run_id)
        ).scalar() or 0

        rhythm_count = self.session.execute(
            select(func.count()).select_from(RhythmCurve).where(RhythmCurve.run_id == run_id)
        ).scalar() or 0

        return chunks_count > 0 and emotion_count >= chunks_count and rhythm_count >= chunks_count
