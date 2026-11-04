"""标注 agent 的完整章级输出契约"""

from pydantic import Field

from src.event_trees.models import BoundEvent
from src.event_trees.vocabulary import RoleFunction
from src.fact_graph.outputs import BoundDialogue, BoundParagraphLabel
from src.fact_graph.schema import StrictModel
from src.metrics.annotation_inputs import ChapterMetricsInput


class BoundCharacterObservation(StrictModel):
    """用于保存从事件人物参与者派生的动态状态"""

    character: str = Field(min_length=1)
    role_function: RoleFunction | None = None
    action: str | None = Field(default=None, min_length=1)
    emotion: int | None = Field(default=None, ge=-2, le=2)



class BoundChapterAnnotation(StrictModel):
    """本章正式标注，实体与关系由独立局部命令提交

    没有可标注段落或覆盖告警时使用空列表，不读取其他版本的载荷
    """

    metrics: ChapterMetricsInput
    character_observations: list[BoundCharacterObservation]
    dialogues: list[BoundDialogue]
    events: list[BoundEvent]
    paragraph_labels: list[BoundParagraphLabel] = Field(default_factory=list)
    # 冻结时系统确定性覆盖告警（如候选>0但载荷为空），仅留痕不阻断
    coverage_warnings: list[str] = Field(default_factory=list)
