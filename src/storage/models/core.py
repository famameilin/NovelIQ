"运行身份与全书统计产出模型"

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.ids import new_id, new_task_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base


class Run(Base):
    "任务身份及模型完成事实"

    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    novelid: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("novels.novel_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    taskid: Mapped[str] = mapped_column(String(8), nullable=False, unique=True, default=new_task_id)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    lda_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    w2v_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class GlobalStats(Base):
    "每个运行一行的全书统计结果"

    __tablename__ = "global_stats"
    run_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    avg_mtld: Mapped[float | None] = mapped_column(Float, nullable=True, comment="平均 MTLD")
    avg_ttr: Mapped[float | None] = mapped_column(Float, nullable=True, comment="平均 TTR")
    avg_sent_len: Mapped[float | None] = mapped_column(Float, nullable=True, comment="平均句长")
    emotion_avg: Mapped[float | None] = mapped_column(Float, nullable=True, comment="情绪均值")
    lexicon_zero_hit_share: Mapped[float | None] = mapped_column(Float, nullable=True, comment="词典零命中占比")
    emotion_std: Mapped[float | None] = mapped_column(Float, nullable=True, comment="情绪标准差")
    emotion_max: Mapped[float | None] = mapped_column(Float, nullable=True, comment="情绪最大值")
    emotion_min: Mapped[float | None] = mapped_column(Float, nullable=True, comment="情绪最小值")
    emotion_peak_chapter_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="情绪峰值章号")
    emotion_min_chapter_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="情绪低谷章号")
    rhythm_avg: Mapped[float | None] = mapped_column(Float, nullable=True, comment="节奏均值")
    rhythm_std: Mapped[float | None] = mapped_column(Float, nullable=True, comment="节奏标准差")
    rhythm_max: Mapped[float | None] = mapped_column(Float, nullable=True, comment="节奏最大值")
    rhythm_min: Mapped[float | None] = mapped_column(Float, nullable=True, comment="节奏最小值")
    rhythm_peak_chapter_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="节奏峰值章号")
    rhythm_min_chapter_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="节奏低谷章号")
