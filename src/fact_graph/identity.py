"关系业务键的端点归一化"

from typing import Any

from src.fact_graph.vocabulary import RELATION_DEFINITIONS


def canonical_relation_key(
    from_entity_id: Any,
    to_entity_id: Any,
    relation_type: str,
) -> tuple[Any, Any, str]:
    "双向关系按端点排序，定向关系保留端点顺序"
    definition = RELATION_DEFINITIONS.get(relation_type)
    if (
        definition is not None
        and definition["directionality"] == "bidirectional"
        and from_entity_id is not None
        and to_entity_id is not None
        and str(from_entity_id) > str(to_entity_id)
    ):
        return to_entity_id, from_entity_id, relation_type
    return from_entity_id, to_entity_id, relation_type
