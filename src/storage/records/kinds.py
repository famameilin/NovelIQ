"存储合同中的封闭标量取值，不包含 ORM 映射"

ANNOTATION_ROLES = ("annotation", "entity", "event", "metric")
ARC_KINDS = ("main", "subplot")
ARC_RELATION_PREFIXES = ("dep:", "sdp:")
CASE_TYPES = ("character", "relation", "dialogue", "event")
CAST_ROLES = ("focus", "main", "core")
CAUSE_ROLES = ("root", "main", "secondary")
DIAGNOSIS_ROLES = ("case", "report")
ENTITY_TYPES = ("character", "location", "item", "organization")
EVENT_STATUSES = ("ongoing", "resolved")
AGENT_TYPES = ("annotation", "entity", "event", "metric", "case", "report")
AGENT_STATUSES = ("running", "success", "error")
FEATURE_LOWESS_NET_DENSITY = "lowess_net_density"
FEATURE_LOWESS_SURFACE_TENSION = "lowess_surface_tension"
FEATURE_POS_VECTOR_PREFIX = "pos_vector:"
FEATURE_SEMANTIC_VECTOR = "semantic_vector"
FEATURE_SENTENCE_CODES = (
    "sentence_short",
    "sentence_medium",
    "sentence_long",
    "sentence_compound",
    "sentence_parallel_candidate",
)
FEATURE_TENSION_Z = "tension_z"
FIELD_ACTIONS = ("omit", "set", "clear")
FIXED_FUNCTION_WORDS = (
    "之",
    "其",
    "者",
    "也",
    "所",
    "以",
    "而",
    "与",
    "则",
    "乃",
    "于",
    "乎",
    "矣",
    "焉",
    "哉",
    "兮",
    "尔",
    "若",
    "为",
    "何",
)
FIXED_SEMANTIC_CATEGORIES = (
    "combat",
    "body",
    "relation",
    "faction",
    "command",
    "action",
    "psychology",
    "measure",
    "emotion",
    "color",
)
FOCUS_STRUCTURES = ("single", "dual", "ensemble")
FORESHADOW_ACTION_TYPES = ("setup", "reinforce", "payoff")
PAYOFF_LIKELIHOODS = ("high", "medium", "low")
TOPIC_INFERENCE_STATUSES = ("complete", "empty_after_preprocess", "empty_bow", "failed")
