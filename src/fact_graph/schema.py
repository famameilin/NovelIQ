"""
章节标注 Agent 语义写入合同与系统绑定模型
"""

# 输入与输出模型只依赖本文件的基础约束，消费者直接导入实际定义模块

# 模型可见文案约定：本模块的类 docstring 会被 pydantic 渲染成字段的 JSON schema 说明，
# 直接进模型可见面（工具参数 schema、程序面 API 目录），一律按"说明"写。

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict


class StrictModel(BaseModel):
    """统一拒绝标注合同中的额外字段"""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


# emotion 合同：五档整数分值 -2..2（模型直接输出数字）

# pivot/cliffhanger 说明单源：写者面 write_metrics 签名、ChapterMetricsInput
# 与 agent 面 metric 构造器目录共用同一份文本（只陈述字段机制，不裁断与 narrative_function 的分工）

# 四个生产引用面使用 EntityNameRef，由运行时解析正文名字与大类
# 下方字符串类型仅保留给其他内部定位面，参与者、关系两端与说话人不再使用它
ENTITY_REF_FIELD_HINT = (
    "（对象={name: 正文名字, entity_type: character/item/location/organization}；"
    "运行时解析，未登记则自动登记；不再写 id）"
)


def _reject_blank_entity_ref(value: object) -> object:
    """用于拒绝空引用；字符串按 el 键或 run 级 id 进入账本解析"""
    if isinstance(value, str) and not value.strip():
        raise ValueError("实体引用不能为空")
    return value


def entity_ref_field_description(label: str) -> str:
    """统一渲染实体引用字段描述（两种键空间与禁令同一文案）"""
    return f"{label}{ENTITY_REF_FIELD_HINT}"


class EntityRefType:
    """把"实体引用"这一注解标记出来

    程序面目录渲染按标记给类型标签（"实体引用"），否则 from_entity 这种字段在签名里
    只能照底层类型写"文本"。注解元数据本身不参与校验。
    """


# 可复用的实体引用类型：供工具签名与参与者数组模型共用（解析见 ledger.resolve_entity_ref）
EntityRef = Annotated[str, BeforeValidator(_reject_blank_entity_ref), EntityRefType()]




# 实体标签约束单源：服务端校验、内部载荷 Field 描述、工具参数说明共用，
# 防止"约束只写在内部载荷模型上、模型可见的工具签名里没有"的两层模型漂移
ENTITY_TAG_MAX_COUNT = 3
ENTITY_TAG_MAX_CHARS = 5
ENTITY_TAGS_RULE_TEXT = f"最多 {ENTITY_TAG_MAX_COUNT} 个，每个最多 {ENTITY_TAG_MAX_CHARS} 个字"

# 两个角色字段的判据（提示词面共用一份：载荷字段说明与程序面目录说明同取这里，
# 拒绝回执只报取值域）
