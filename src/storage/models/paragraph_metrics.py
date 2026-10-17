"""
段落指标表 ORM 模型定义（2026-10-16 全库 3NF 改造）

paragraph_metrics 是同一段落键下原始计数、阶段完成事实与推断状态的唯一落点：
- 原指标充分统计量（分子/分母）与真实指标计算时间
- 预处理观测时间、语言完成时间、短语完成时间（完成事实，不靠非空推断）
- 固定功能词 20 个明确计数列、固定语义分类 10 个明确计数列（目录穷举，
  不建任意 category/value 仓库）
- 独立监督观测（边界打分和）与主题推断 token 数/状态/真实异常

char_count（读取投影）、密度、张力 z/sigmoid 与 LOWESS 值不在本表；
句式五个分类计数进 paragraph_features；预处理与指标同批 token 已核实同义，
只留 token_count 一个口径，LTP 词元数从 linguistic_spans 行数取得。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

#: 主题推断状态封闭取值：complete / empty_after_preprocess / empty_bow / failed
TOPIC_INFERENCE_STATUSES = ("complete", "empty_after_preprocess", "empty_bow", "failed")

#: 固定功能词计数列（20 个古典功能词；目录按合同穷举，不接纳任意类别名）
FIXED_FUNCTION_WORDS = (
    "之", "其", "者", "也", "所", "以", "而", "与", "则", "乃",
    "于", "乎", "矣", "焉", "哉", "兮", "尔", "若", "为", "何",
)

#: 固定语义分类计数列（10 个语义类别；目录按合同穷举）
FIXED_SEMANTIC_CATEGORIES = (
    "combat", "body", "relation", "faction", "command",
    "action", "psychology", "measure", "emotion", "color",
)


class ParagraphMetric(Base):
    """
    段落指标表（原始计数、阶段完成事实与推断状态）

    每行对应一个真实段落（paragraphs 为唯一事实源），
    章节/全书汇总必须从本表分子分母聚合，禁止平均段落密度。
    """

    __tablename__ = "paragraph_metrics"
    __table_args__ = (
        CheckConstraint(
            "inference_status IS NULL OR inference_status IN "
            "('complete', 'empty_after_preprocess', 'empty_bow', 'failed')",
            name="ck_paragraph_metrics_inference_status",
        ),
        CheckConstraint(
            "inference_status IS DISTINCT FROM 'complete' "
            "OR (inference_token_count IS NOT NULL AND inference_token_count > 0)",
            name="ck_paragraph_metrics_complete_token_positive",
        ),
        ForeignKeyConstraint(
            ["run_id", "paragraph_id"],
            ["paragraphs.run_id", "paragraphs.paragraph_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            ondelete="CASCADE",
        ),
        Index("idx_paragraph_metrics_run_paragraph", "run_id", "paragraph_id"),
        {"comment": "段落指标表：原始计数/阶段完成事实/推断状态（密度与派生值读取计算）"},
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="所属分析运行")
    paragraph_id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="所属段落编号")

    # 原指标充分统计量（指标算法口径；预处理 tokenizer 与指标同批，共用该计数）
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="token 数（分母）")
    sentence_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="句数")
    sentence_char_sum: Mapped[float | None] = mapped_column(Float, nullable=True, comment="句长字符和")
    sentence_char_sum_sq: Mapped[float | None] = mapped_column(Float, nullable=True, comment="句长字符平方和")
    positive_weight_sum: Mapped[float | None] = mapped_column(Float, nullable=True, comment="正向情绪权重命中和")
    negative_weight_sum: Mapped[float | None] = mapped_column(Float, nullable=True, comment="负向情绪权重命中和")
    fight_weight_sum: Mapped[float | None] = mapped_column(Float, nullable=True, comment="战斗权重命中和")
    exclaim_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="感叹号数")
    question_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="问号数")
    pause_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="停顿标点数")
    dialogue_char_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="对话字符数")
    sensory_hit_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="感官词命中数")
    imagery_hit_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="意象词命中数")
    metaphor_sentence_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="比喻句数")
    body_reaction_hit_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="身体反应转喻命中数（不进正负极性）"
    )
    metrics_created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="指标计算真实时间"
    )

    # 预处理/完成事实（完成但零计数必须是 0；未产生该组观测为空）
    preprocess_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="预处理观测真实时间"
    )
    linguistic_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="语言处理完成时间"
    )
    phrase_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="短语匹配完成时间"
    )

    # 固定功能词计数（20 列；token 命中计数）
    fw_之: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「之」计数")
    fw_其: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「其」计数")
    fw_者: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「者」计数")
    fw_也: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「也」计数")
    fw_所: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「所」计数")
    fw_以: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「以」计数")
    fw_而: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「而」计数")
    fw_与: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「与」计数")
    fw_则: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「则」计数")
    fw_乃: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「乃」计数")
    fw_于: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「于」计数")
    fw_乎: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「乎」计数")
    fw_矣: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「矣」计数")
    fw_焉: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「焉」计数")
    fw_哉: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「哉」计数")
    fw_兮: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「兮」计数")
    fw_尔: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「尔」计数")
    fw_若: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「若」计数")
    fw_为: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「为」计数")
    fw_何: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="功能词「何」计数")

    # 固定语义分类计数（10 列）
    semantic_combat: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="语义分类 combat 命中数")
    semantic_body: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="语义分类 body 命中数")
    semantic_relation: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="语义分类 relation 命中数")
    semantic_faction: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="语义分类 faction 命中数")
    semantic_command: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="语义分类 command 命中数")
    semantic_action: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="语义分类 action 命中数")
    semantic_psychology: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="语义分类 psychology 命中数"
    )
    semantic_measure: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="语义分类 measure 命中数")
    semantic_emotion: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="语义分类 emotion 命中数")
    semantic_color: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="语义分类 color 命中数")

    # 独立监督观测（真实打分；标签不足为 NULL，不用默认常量）
    boundary_pos_score_sum: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="边界打分正向和（标签不足为 NULL）"
    )
    boundary_neg_score_sum: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="边界打分负向和（标签不足为 NULL）"
    )

    # 主题推断事实（固定原因不落列；真实异常才入 error_text）
    inference_token_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="进入 LDA BOW 的 token 数（聚合分母）"
    )
    inference_status: Mapped[str | None] = mapped_column(
        String(30), nullable=True,
        comment="推断状态（complete/empty_after_preprocess/empty_bow/failed）",
    )
    inference_error_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="真实异常文字")
    inference_created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="推断状态写入时间"
    )

    def __repr__(self) -> str:
        return f"<ParagraphMetric(run_id={self.run_id}, paragraph_id={self.paragraph_id})>"
