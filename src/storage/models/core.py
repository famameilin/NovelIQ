"分析运行表 ORM 模型定义（2026-10-16 全库 3NF 改造）"

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.config.constants.contracts import FIXED_CONTRACT_VERSION
from src.storage.ids import new_id, new_task_id
from src.storage.uuid_type import Uuid7 as Uuid

from .base import Base


class AnalysisRun(Base):
    "分析运行记录表"

    __tablename__ = "analysis_runs"
    __table_args__ = (
        Index("idx_analysis_runs_novel", "novel_id"),
        Index("idx_analysis_runs_status", "status"),
        {"comment": "分析运行表：运行身份/调度/来源观察/合同/模型构建/阶段完成与具名全书统计"},
    )

    run_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, comment="运行主键（uuid）", default=new_id, autoincrement=False
    )
    novel_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("novels.novel_id", ondelete="RESTRICT", name="analysis_runs_novel_id_fkey"),
        nullable=False,
        comment="所属小说",
    )
    task_id: Mapped[str] = mapped_column(
        String(8), nullable=False, unique=True, default=new_task_id, comment="独立的 8 位任务短 ID"
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", comment="运行状态")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="总进度（0~1）")
    stage: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="当前主阶段名")

    # 运行态字段
    sub_stage: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None, comment="当前子阶段名")
    current: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="子阶段已完成单位数")
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=100, comment="子阶段总单位数")
    message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, comment="进度消息")
    error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None, comment="失败时的错误信息")
    task_kind: Mapped[str] = mapped_column(String(50), nullable=False, default="analysis", comment="任务类型")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="取消请求标志")
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None, comment="执行者标识")
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None, comment="心跳时间")
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        default=None,
        comment="实际开始执行时间",
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None, comment="完成时间")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="创建时间")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="更新时间")

    # 运行开始时来源观察（运行时快照，不随小说登记行后续改动）
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True, comment="本次运行实际读取的源路径观察")
    source_title: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="本次运行的书名观察")
    source_author: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="本次运行的作者观察")

    # 实际提交的重分析请求（无请求为该组全空；false 为实际提交）
    force_preprocess: Mapped[bool | None] = mapped_column(Boolean, nullable=True, comment="强制重跑预处理请求")
    force_annotate: Mapped[bool | None] = mapped_column(Boolean, nullable=True, comment="强制重跑标注请求")
    force_aggregate: Mapped[bool | None] = mapped_column(Boolean, nullable=True, comment="强制重跑聚合请求")
    force_topic_model: Mapped[bool | None] = mapped_column(Boolean, nullable=True, comment="强制重跑主题模型请求")
    force_diagnose: Mapped[bool | None] = mapped_column(Boolean, nullable=True, comment="强制重跑诊断请求")
    force_linguistic: Mapped[bool | None] = mapped_column(Boolean, nullable=True, comment="强制重跑语言结构请求")
    requested_num_topics: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="请求主题数（请求口径，不代表实际 K）"
    )

    # 运行级正式合同（固定合同版本与各实际来源观察）
    contract_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default=FIXED_CONTRACT_VERSION,
        comment="运行级固定合同版本（实体关系/短语规则/主题状态/归一映射）",
    )
    embedding_model_key: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="实际嵌入模型 key")
    ltp_pipeline_version: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="实际 LTP 管线版本")
    ltp_model_key: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="实际 LTP 模型 key")
    fixed_phrase_lexicon_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="实际固定短语词表 key"
    )
    fixed_phrase_contract_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="实际固定短语计量合同版本"
    )
    curve_bandwidth: Mapped[float | None] = mapped_column(Float, nullable=True, comment="LOWESS 带宽参数")
    curve_min_points: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="LOWESS 最少点数")

    # Word2Vec 实际构建（每启用一次 run 一组具名参数）
    w2v_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="词向量维度")
    w2v_vocabulary_size: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="词表规模")
    w2v_source_uri: Mapped[str | None] = mapped_column(Text, nullable=True, comment="预训练来源（自训练为 NULL）")
    w2v_license_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="预训练许可名称")
    w2v_training_document_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="训练文档数")
    w2v_training_token_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="训练 token 数")
    w2v_window_size: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="训练窗口大小")
    w2v_min_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="最低词频")
    w2v_epochs: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="训练轮数")
    w2v_pretrained_vocabulary_size: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="预训练词表规模")
    w2v_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="词向量构建时间")

    # LDA 实际构建（实际 K 不与请求 K 混淆）
    lda_library_version: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="建模库版本")
    lda_pipeline_version: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="预处理管线版本")
    lda_num_topics: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="实际主题数 K")
    lda_dictionary_size: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="词典规模")
    lda_training_document_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="训练文档数")
    lda_passes: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="LDA passes")
    lda_iterations: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="LDA iterations")
    lda_alpha: Mapped[float | None] = mapped_column(Float, nullable=True, comment="LDA alpha（标量）")
    lda_eta: Mapped[float | None] = mapped_column(Float, nullable=True, comment="LDA eta（标量）")
    lda_random_state: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="随机种子")
    lda_batch_size: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="批大小")
    lda_minimum_probability: Mapped[float | None] = mapped_column(Float, nullable=True, comment="最小概率")
    lda_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="LDA 构建时间")

    # 实际阶段完成及并发栅栏（完成事实不能靠某个数非空判断）
    preprocess_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="预处理真实完成时间"
    )
    linguistic_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="语言结构真实完成时间"
    )
    curve_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="曲线计算真实完成时间")
    aggregate_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="全书聚合真实完成时间"
    )
    topic_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="主题建模真实完成时间")
    guard_generation: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
        comment="并发栅栏代次（受约束写入事务内递增取锁）",
    )

    # 全书统计：16 个明确列（正式聚合写一次；极值并列取最后段落）
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

    def __repr__(self) -> str:
        return (
            f"<AnalysisRun(run_id={self.run_id}, novel_id={self.novel_id}, "
            f"status={self.status}, progress={self.progress})>"
        )
