"""
标注相关配置

创建时间: 2026-03-17
创建者: TraeAI
任务: code-quality-refactor - 消除魔法数字/字符串
说明: 集中管理标注客户端的常量配置

修改时间: 2026-03-18
修改者: TraeAI
任务: entity-type-relation-extraction
修改内容:
- 重命名 valid_relation_types 为 valid_interpersonal_relation_types
- 新增 valid_hierarchical_relation_types（层级关系类型）
- 新增 valid_entity_types（实体类型）

修改时间: 2026-03-28
修改者: TraeAI
任务: fix-relation-type-annotation
修改内容: 新增"友情"关系类型，解决童年玩伴被误标为"家族"的问题
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AnnotationConfig:
    """
    标注配置常量

    创建时间: 2026-03-17
    创建者: TraeAI
    任务: code-quality-refactor - 消除魔法数字

    修改时间: 2026-03-18
    修改者: TraeAI
    任务: entity-type-relation-extraction
    修改内容: 新增层级关系类型和实体类型配置

    修改时间: 2026-03-19
    修改者: TraeAI
    任务: 修复mypy类型错误
    修改内容: 将List[str]改为Optional[List[str]]以兼容None默认值
    """

    # 重试配置
    phase_max_retries: int = 3
    disambig_max_retries: int = 3
    validation_max_retries: int = 3

    # 检查点配置
    checkpoint_interval: int = 50

    # 上下文配置
    prev_chunks: int = 3
    last_n_chunks: int = 10
    lookback: int = 10

    # 验证配置
    valid_role_functions: list[str] | None = None
    valid_action_types: list[str] | None = None
    valid_emotion_scores: list[str] | None = None
    valid_interpersonal_relation_types: list[str] | None = None
    valid_hierarchical_relation_types: list[str] | None = None
    valid_entity_types: list[str] | None = None
    valid_clue_types: list[str] | None = None
    valid_event_types: list[str] | None = None
    valid_foreshadowing_types: list[str] | None = None

    def __post_init__(self):
        # 由于frozen=True，使用object.__setattr__来设置默认值
        if self.valid_role_functions is None:
            object.__setattr__(self, "valid_role_functions", ["主体", "客体", "发送者", "接收者", "帮助者", "反对者"])
        if self.valid_action_types is None:
            object.__setattr__(self, "valid_action_types", ["战斗", "逃跑", "对话", "决策", "移动", "情感", "其他"])
        if self.valid_emotion_scores is None:
            object.__setattr__(
                self,
                "valid_emotion_scores",
                ["strong_positive", "mild_positive", "neutral", "mild_negative", "strong_negative"],
            )
        if self.valid_interpersonal_relation_types is None:
            object.__setattr__(
                self,
                "valid_interpersonal_relation_types",
                ["师徒", "敌对", "盟友", "爱慕", "家族", "利益", "主从", "友情"],
            )
        if self.valid_hierarchical_relation_types is None:
            object.__setattr__(
                self,
                "valid_hierarchical_relation_types",
                [
                    "belongs_to",
                    "member_of",
                    "leader_of",
                    "affiliated_with",
                    "father_of",
                    "son_of",
                    "parent_of",
                    "child_of",
                    "sibling_of",
                    "spouse_of",
                ],
            )
        if self.valid_entity_types is None:
            object.__setattr__(self, "valid_entity_types", ["character", "group", "organization"])
        if self.valid_clue_types is None:
            object.__setattr__(
                self,
                "valid_clue_types",
                [
                    "none",
                    "self_introduction",
                    "named_by_other",
                    "alias_revealed",
                    "appearance_desc",
                    "unique_body_marker",
                    "kinship_identity",
                    "naming_scene",
                ],
            )
        if self.valid_event_types is None:
            object.__setattr__(self, "valid_event_types", ["冲突", "铺垫", "转折"])
        if self.valid_foreshadowing_types is None:
            object.__setattr__(self, "valid_foreshadowing_types", ["causal", "thematic"])


# 全局实例
ANNOTATION_CONFIG = AnnotationConfig()
