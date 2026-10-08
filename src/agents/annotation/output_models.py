"""标注 agent 的完整章级输出契约"""

from pydantic import Field

from src.event_trees.models import BoundEvent
from src.fact_graph.inputs import ChapterMetricsInput
from src.fact_graph.outputs import BoundCharacterObservation, BoundDialogue, BoundParagraphLabel
from src.fact_graph.schema import StrictModel


class BoundChapterAnnotation(StrictModel):
    """本章正式标注，实体与关系由独立局部命令提交

    没有可标注段落或覆盖告警时使用空列表，不读取其他版本的载荷
    """

    metrics: ChapterMetricsInput
    character_observations: list[BoundCharacterObservation]
    dialogues: list[BoundDialogue]
    events: list[BoundEvent]
    paragraph_labels: list[BoundParagraphLabel] = Field(default_factory=list)
    # 2026-09-05 冻结时系统确定性覆盖告警（如候选>0但载荷为空），仅留痕不阻断
    coverage_warnings: list[str] = Field(default_factory=list)
