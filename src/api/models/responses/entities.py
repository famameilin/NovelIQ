"""实体/短语/词向量响应模型：LTP 实体候选、固定短语命中、词向量契约与词性覆盖率/质心、
角色/层级实体关系
"""

from pydantic import BaseModel, Field


class CharacterRelation(BaseModel):
    chapter_id: int
    from_char: str
    to_char: str
    type: str
    change: str


class HierarchicalRelation(BaseModel):
    """
    层级关系模型
    """

    rel_id: str
    rel_type: str
    first_chapter: int | None = None
    last_chapter: int | None = None
    from_entity: str
    to_entity: str


class EntityCandidate(BaseModel):
    paragraph_id: int
    surface_text: str
    raw_entity_type: str
    normalized_entity_type: str | None
    local_start_char: int
    local_end_char: int


class LinguisticEntitiesResponse(BaseModel):
    """LTP 实体候选（审核面数据源）"""

    run_id: str
    source_kind: str = "ltp"
    entities: list[EntityCandidate] = Field(default_factory=list)
    count_by_type: dict[str, int] = Field(default_factory=dict)
    unavailable_reason: str | None = None


class LinguisticPhrasesResponse(BaseModel):
    """固定短语命中统计：正式密度与四字候选分开"""

    run_id: str
    total_char_count: int = 0
    metric_hit_count: int = 0
    fixed_phrase_density: float | None = None
    four_char_candidate_count: int = 0
    total_hits: int = 0
    unavailable_reason: str | None = None


class Word2VecModelInfo(BaseModel):
    embedding_dimension: int
    vocabulary_size: int
    artifact_scope: str


class PosCoverageEntry(BaseModel):
    pos_group: str
    source_token_total: int
    in_vocabulary_token_total: int
    coverage_ratio: float | None = None


class PosCentroidEntry(BaseModel):
    pos_group: str
    weighted_token_total: int
    embedding_vector: list[float]


class Word2VecStatsResponse(BaseModel):
    """词向量契约与词性覆盖率/质心

    pos_similarity_matrix 与 pos_centroids 行序一致（按 pos_group 升序），
    为组间余弦相似度对称矩阵（对角线为 1）；质心少于 2 组时为 null。
    """

    run_id: str
    model: Word2VecModelInfo | None = None
    pos_coverage: list[PosCoverageEntry] = Field(default_factory=list)
    pos_centroids: list[PosCentroidEntry] = Field(default_factory=list)
    pos_similarity_matrix: list[list[float]] | None = None
    unavailable_reason: str | None = None
