"主题模型产物属性"

from dataclasses import dataclass


@dataclass(frozen=True)
class TopicModelRunContract:
    "实际模型及正式推断产出"

    run_id: str
    num_topics: int
    dictionary_size: int
    inference_paragraph_count: int
    artifact_key: str
