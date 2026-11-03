"""逐段语言统计的封闭存储种类"""

LINGUISTIC_COUNT_FIELDS = (
    "ltp_token_count", "dependency_node_count", "dependency_root_count", "dependency_depth_sum", "dependency_depth_max",
)
LINGUISTIC_SCALAR_FIELDS = ("lexicon_pos_count", "lexicon_neg_count", "mneg_pos_count", "mneg_neg_count")
WORD_LENGTH_KEYS = ("1", "2", "3", "4", "5_plus")
LINGUISTIC_GROUP_PREFIXES = {
    "word_length_counts": "word_length:",
    "pos_counts": "pos_count:",
    "dependency_relation_counts": "dep_relation:",
}
SENTENCE_CODE_TO_KEY = {
    "sentence_short": "short",
    "sentence_medium": "medium",
    "sentence_long": "long",
    "sentence_compound": "compound",
    "sentence_parallel_candidate": "parallel_candidate",
}
LINGUISTIC_REQUIRED_CODES = (
    *LINGUISTIC_COUNT_FIELDS, *LINGUISTIC_SCALAR_FIELDS,
    *(f"word_length:{key}" for key in WORD_LENGTH_KEYS), *SENTENCE_CODE_TO_KEY,
)
