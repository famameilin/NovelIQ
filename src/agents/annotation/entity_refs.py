"""名字引用的唯一登记入口，复用正式实体生成原语"""

from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import EntityInput
from src.fact_graph.vocabulary import EntityType


def ensure_entity_ref(graph: FactGraph, name: str, entity_type: EntityType, *, chapter_id: int) -> str:
    """返回名字与大类的原始身份键，缺失时登记；调用者须持有 Agent 写锁与当前作者上下文

    事件、关系、对话引用在此跨入实体域，仍经 register_entities 和 record_entity_ops
    记录当前 work 的贡献，随既有事务保存或撤销，不新增跨域写通道
    """
    entity = EntityInput(name=name, entity_type=entity_type)
    key = graph.entity_key(entity.name, entity.entity_type)
    if key not in graph.entity_types:
        graph.register_entities([entity])
    # 每个引用作者保留自己的支持，先登记的车道撤销不能带走另一车道的有效端点
    graph.record_entity_ops([entity], chapter_id=chapter_id, identity_only=True)
    return key
