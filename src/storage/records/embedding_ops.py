"段落写入与检索使用的普通记录"

from dataclasses import dataclass


@dataclass(frozen=True)
class ParagraphEmbeddingRow:
    "用于批量写入自然段向量（二期段落化：段落身份 + 向量）"

    paragraph_id: int
    embedding_vector: list[float]


@dataclass(frozen=True)
class SimilarParagraphRow:
    "用于返回自然段语义定位结果（JOIN paragraphs 取身份与坐标）"

    paragraph_id: int
    chapter_id: int
    paragraph_text: str
    local_start_char: int
    local_end_char: int
    global_start_char: int
    global_end_char: int
    similarity: float
