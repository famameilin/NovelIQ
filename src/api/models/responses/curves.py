"""
段落曲线响应模型

创建时间: 2026-10-02
创建者: Trae
任务: 大文件拆分（models/responses.py → responses/ 包）
说明: 自 src/api/models/responses.py 拆出段落曲线与情绪趋势窗口响应模型
（设计文档《章节粒度分析指标重设计》§13.1 展示层），字段与语义保持不变。
"""

from pydantic import BaseModel


class ParagraphCurvePoint(BaseModel):
    """段落曲线点（设计文档《章节粒度分析指标重设计》§13.1）"""

    paragraph_id: int
    chapter_id: int
    paragraph_index: int
    global_start_char: int
    global_end_char: int
    position: float
    char_count: int
    token_count: int
    pos_density: float | None = None
    neg_density: float | None = None
    net_density: float | None = None
    smoothed_net_density: float | None = None
    surface_tension: float | None = None
    smoothed_surface_tension: float | None = None


class EmotionTrendWindow(BaseModel):
    """情绪趋势窗口（§13.1 展示层：缩放自适应窗口聚合，由段落充分统计量计算）

    - 覆盖率为窗内命中段占比，值域 [0,1]，不受段长稀释
    - 池化密度为窗内分子/分母聚合（§8.1），禁止等权平均段落密度
    - position 语义与 ParagraphCurvePoint 一致（段落中点 / 全书字符数）
    """

    window_index: int
    position: float
    start_position: float
    end_position: float
    paragraph_start: int
    paragraph_end: int
    chapter_start: int
    chapter_end: int
    pos_coverage: float
    neg_coverage: float
    pooled_pos_density: float | None = None
    pooled_neg_density: float | None = None
    pooled_net_density: float | None = None
    smoothed_pos_coverage: float | None = None
    smoothed_neg_coverage: float | None = None
    smoothed_pooled_pos_density: float | None = None
    smoothed_pooled_neg_density: float | None = None
    smoothed_pooled_net_density: float | None = None
    token_total: int
    hit_paragraphs: int
    paragraph_total: int
