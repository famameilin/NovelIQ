"""
章节标注 Agent 语义写入合同与系统绑定模型
"""

# 输入与输出模型只依赖本文件的基础约束，消费者直接导入实际定义模块

# 2026-09-17 模型可见文案约定：本模块的类 docstring 会被 pydantic 渲染成字段的
# JSON schema 说明、直接进模型可见面（工具参数 schema、程序面 API 目录都是这份），
# 所以 docstring 一律按"说明"写——这是什么字段、能取哪些值、怎么判；开发史、
# 裁决过程、实测数字写成类上方的 # 注释，不进模型面。

from __future__ import annotations

import unicodedata
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict


class StrictModel(BaseModel):
    """2026-08-07 用于统一拒绝标注合同中的额外字段"""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


# 2026-09-11 emotion 合同：五档整数分值 -2..2（模型直接输出数字，删除词表映射的解码回合）
EMOTION_SCORE_DESCRIPTION = (
    "情绪方向与强度分值，整数 -2..2"
    "（-2 强烈负面 / -1 轻微负面 / 0 中性 / 1 轻微正面 / 2 强烈正面）"
)

# 2026-09-18 pivot/cliffhanger 说明单源：写者面 write_metrics 签名、ChapterMetricsInput
# 与 subagent 面 metric 构造器目录共用同一份文本（只陈述字段机制，不裁断与 narrative_function 的分工）
# 2026-09-18 说明改为判据口径：原句把"全书按 pivot_moment=true 的章数÷有效章数算
# chapter_pivot_rate"这类聚合公式写给模型，模型据此判不了任何一段正文；聚合口径属指标文档
# （src/config/constants/metrics_contracts.py 的 chapter_pivot_rate 条目）。
PIVOT_MOMENT_DESCRIPTION = (
    "本章是否标记为叙事转折点（布尔，独立字段）。narrative_function 说的是本章自身的叙事功能，"
    "本字段说的是本章是否构成转折点，两者各自判断、允许不一致。"
)
CLIFFHANGER_DESCRIPTION = "本章是否以悬念收尾（布尔，追读钩子）。"

# 2026-10-02 wire 常量单源（原 tools 的 _EL_PATH_SEP/_ROOT_NODE_KEY 与 subagent_ir 的
# EL_PATH_SEP/RESERVED_ROOT_KEY 双份定义收编于此，包内公共）：局部键路径分隔符与事件
# 根节点保留键——子事件 el = "<树键>/<节点键>"，根事件 el = 树键，节点键不得占用 root。
EL_PATH_SEP = "/"
RESERVED_ROOT_KEY = "root"


# 2026-09-19 id 纪律：实体引用 = run 级 uuid id 或本 章内 write_entity 自定的 el 键。
# el 由模型指定、登记即绑定（同回合后面的调用直接可用，不等回执）；id 由服务端确定性铸造、
# 回执与检索视图同值；名称仍是非法引用，在账本解析点按 unknown_el / unknown_entity_id 拒绝。
ENTITY_REF_FIELD_HINT = (
    "（字符串=write_entity 回执里的 run 级 id；"
    "或本章 write_entity 自定的 el 键；不接受实体名称）"
)


def _reject_blank_entity_ref(value: object) -> object:
    """用于拒绝空引用；字符串按 el 键或 run 级 id 进入账本解析"""
    if isinstance(value, str) and not value.strip():
        raise ValueError("实体引用不能为空")
    return value


def entity_ref_field_description(label: str) -> str:
    """2026-09-14 用于统一渲染实体引用字段描述（两种键空间与禁令同一文案）"""
    return f"{label}{ENTITY_REF_FIELD_HINT}"


class EntityRefType:
    """2026-09-20 用于把"实体引用"这一注解标记出来

    程序面目录渲染按标记给类型标签（"实体引用"），否则 from_entity 这种字段在签名里
    只能照底层类型写"文本"——引用写什么正是被拒最多的那一族（run 54a72932：写者面
    295 次 write_relation 失败里 135 次填的是实体名称）。注解元数据本身不参与校验。
    """


# 可复用的实体引用类型：供工具签名与参与者数组模型共用（解析见 ledger.resolve_entity_ref）
EntityRef = Annotated[str, BeforeValidator(_reject_blank_entity_ref), EntityRefType()]


def normalize_semantic_text(value: str, *, label: str) -> str:
    """2026-08-07 用于统一规范化 Agent 提交的人类可读文本"""
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        raise ValueError(f"{label} 不能为空")
    return normalized


# 2026-09-13 实体标签约束单源：服务端校验、内部载荷 Field 描述、工具参数说明共用，
# 防止"约束只写在内部载荷模型上、模型可见的工具签名里没有"的两层模型漂移
# （run 1b388eb3 第 2 章实锤：模型写 6 字标签"情报头子之子"被拒，回执只报长度、
# 工具面上查不到该规则，模型原样重试后又放弃）
ENTITY_TAG_MAX_COUNT = 3
ENTITY_TAG_MAX_CHARS = 5
ENTITY_TAGS_RULE_TEXT = f"最多 {ENTITY_TAG_MAX_COUNT} 个，每个最多 {ENTITY_TAG_MAX_CHARS} 个字"

# 2026-09-20 两个角色字段的判据（提示词面共用一份：载荷字段说明与程序面目录说明同取这里，
# 拒绝回执只报取值域）。run 54a72932 的 128 次 write_event 失败里，除漏填外主要是把身份
# 称号写进 role（如"大少爷"）与把 role 的词写进 narrative_role。
EVENT_ROLE_FIELD_HINT = "这个实体在这件事里起的作用，不是身份、称号"
PERSON_ROLE_FIELD_HINT = "与 role 同一判断的叙事面"
