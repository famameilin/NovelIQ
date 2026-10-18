"Storage 的普通字段快照，不携带 ORM 或活动连接"

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ModelCallRecord:
    "ModelCall 的持久化事实快照"

    call_id: str
    model: str
    status: str
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    message_key: str | None
    execution_id: str | None
    turn_index: int | None
    standalone_run_id: str | None
    standalone_chapter_id: int | None
    standalone_task_type: str | None
    standalone_call_type: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    cache_read_tokens: int | None
    reasoning_tokens: int | None
    accounting_source: str | None
    reported_total_tokens: int | None
    cost: float | None
    ttft_ms: int | None
    first_visible_ms: int | None
    reasoning_ms: int | None
    model_ms: int | None
    tool_wall_ms: int | None
    request_messages_bytes: bytes | None
    raw_response_bytes: bytes | None
    context_observed_bytes: bytes | None
    timing_notes_bytes: bytes | None


@dataclass(frozen=True, slots=True)
class AgentToolCallRecord:
    "AgentToolCall 的持久化事实快照"

    id: str
    call_id: str
    tool_name: str
    call_index: int
    status: str
    error: str | None
    started_at: datetime
    tool_duration_ms: int | None
    message_key: str | None
    raw_args_bytes: bytes | None
    executed_args_bytes: bytes | None
    response_observed_bytes: bytes | None
    receipt_observed_bytes: bytes | None


@dataclass(frozen=True, slots=True)
class EventOutboxRecord:
    message_key: str
    """EventOutbox 的持久化事实快照"""
    event_id: str
    stream_id: int
    run_id: str
    chapter_id: int | None
    event_type: str
    emitted_bytes: bytes
    created_at: datetime
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class BookCaseRecord:
    "BookCase 的持久化事实快照"

    case_id: str
    registration_run_id: str | None
    case_type: str
    description: str
    created_at: datetime
    automatic_declaration_id: str | None
    entity_target_id: str | None
    relation_target_id: str | None
    dialogue_target_id: str | None
    declaration_target_id: str | None
    complete_event_target_id: str | None
    pending_event_entry_id: str | None
    dialogue_candidate_chapter_id: int | None
    dialogue_candidate_start: int | None
    dialogue_candidate_end: int | None
    registration_reason: str | None
    registration_paragraph_id: int | None
    review_state: str | None


@dataclass(frozen=True, slots=True)
class CaseEntryRecord:
    "CaseEntry 的持久化事实快照"

    entry_id: str
    case_id: str | None
    producer_execution_id: str | None
    program_work_id: str | None
    parent_entry_id: str | None
    adopted: bool | None
    business_call_id: str | None
    accepted_order: int | None
    tool_name: str | None
    receipt_bytes: bytes | None
    narrative_link_id: str | None
    warning_record_id: str | None
    warning_report_id: str | None
    warning_ordinal: int | None
    attempted_case_reference: str | None
    warning_message: str | None
    candidate_producer_execution_id: str | None
    pending_event_reference: str | None
    pending_event_title: str | None
    pending_event_chapter_id: int | None


@dataclass(frozen=True, slots=True)
class ChapterRecord:
    "Chapter 的持久化事实快照"

    id: str
    run_id: str
    chapter_id: int
    sequence: int
    title: str
    display_title: str
    display_index_label: str | None
    level: str
    start_pos: int
    end_pos: int
    text: str | None
    char_offset: int | None


@dataclass(frozen=True, slots=True)
class AnalysisRunRecord:
    task_id: str
    """AnalysisRun 的持久化事实快照"""
    run_id: str
    novel_id: str
    status: str
    progress: float
    stage: str | None
    sub_stage: str | None
    current: int
    total: int
    message: str | None
    error: str | None
    task_kind: str
    cancel_requested: bool
    worker_id: str | None
    heartbeat_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None
    source_path: str | None
    source_title: str | None
    source_author: str | None
    force_preprocess: bool | None
    force_annotate: bool | None
    force_aggregate: bool | None
    force_topic_model: bool | None
    force_diagnose: bool | None
    force_linguistic: bool | None
    requested_num_topics: int | None
    contract_version: str
    embedding_model_key: str | None
    ltp_pipeline_version: str | None
    ltp_model_key: str | None
    fixed_phrase_lexicon_key: str | None
    fixed_phrase_contract_version: str | None
    curve_bandwidth: float | None
    curve_min_points: int | None
    w2v_dimension: int | None
    w2v_vocabulary_size: int | None
    w2v_source_uri: str | None
    w2v_license_name: str | None
    w2v_training_document_count: int | None
    w2v_training_token_count: int | None
    w2v_window_size: int | None
    w2v_min_count: int | None
    w2v_epochs: int | None
    w2v_pretrained_vocabulary_size: int | None
    w2v_created_at: datetime | None
    lda_library_version: str | None
    lda_pipeline_version: str | None
    lda_num_topics: int | None
    lda_dictionary_size: int | None
    lda_training_document_count: int | None
    lda_passes: int | None
    lda_iterations: int | None
    lda_alpha: float | None
    lda_eta: float | None
    lda_random_state: int | None
    lda_batch_size: int | None
    lda_minimum_probability: float | None
    lda_created_at: datetime | None
    preprocess_completed_at: datetime | None
    linguistic_completed_at: datetime | None
    curve_completed_at: datetime | None
    aggregate_completed_at: datetime | None
    topic_completed_at: datetime | None
    guard_generation: int
    avg_mtld: float | None
    avg_ttr: float | None
    avg_sent_len: float | None
    emotion_avg: float | None
    lexicon_zero_hit_share: float | None
    emotion_std: float | None
    emotion_max: float | None
    emotion_min: float | None
    emotion_peak_chapter_id: int | None
    emotion_min_chapter_id: int | None
    rhythm_avg: float | None
    rhythm_std: float | None
    rhythm_max: float | None
    rhythm_min: float | None
    rhythm_peak_chapter_id: int | None
    rhythm_min_chapter_id: int | None


@dataclass(frozen=True, slots=True)
class DialogueRecordRecord:
    "DialogueRecord 的持久化事实快照"

    dialogue_id: str
    run_id: str
    chapter_id: int
    creation_execution_id: str
    candidate_key: str
    start_char: int
    end_char: int
    current_attribution_execution_id: str | None
    speaker_entity_id: str | None
    tone: str | None
    is_inner_monologue: bool
    related_declaration_id: str | None
    related_complete_event_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EventDeclarationRecord:
    "EventDeclaration 的持久化事实快照"

    declaration_id: str
    record_id: str
    local_key: str
    title: str
    problem: str
    summary: str
    event_type: str
    status: str
    progress: str | None
    is_foreshadowing_root: bool
    payoff_likelihood: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DeclarationParticipantRecord:
    "DeclarationParticipant 的持久化事实快照"

    participant_id: str
    declaration_id: str
    participant_ordinal: int
    entity_id: str
    role: str
    narrative_role: str | None
    action: str | None
    emotion: int | None


@dataclass(frozen=True, slots=True)
class CompleteEventRecord:
    "CompleteEvent 的持久化事实快照"

    event_id: str
    producer_execution_id: str
    local_key: str
    identity_reason: str


@dataclass(frozen=True, slots=True)
class EventRevisionRecord:
    "EventRevision 的持久化事实快照"

    revision_id: str
    event_id: str
    stage_index: int
    declaration_id: str | None
    origin_title: str | None
    origin_problem: str | None
    origin_summary: str | None
    origin_event_type: str | None
    origin_status: str | None
    origin_progress: str | None


@dataclass(frozen=True, slots=True)
class GraphEntityRecord:
    "GraphEntity 的持久化事实快照"

    entity_id: str
    run_id: str
    canonical_name: str
    entity_type: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class GraphRelationRecord:
    "GraphRelation 的持久化事实快照"

    relation_id: str
    from_entity_id: str
    to_entity_id: str
    relation_type: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class GraphFactRecord:
    "GraphFact 的持久化事实快照"

    graph_fact_id: str
    direct_producer_execution_id: str | None
    program_work_id: str | None
    operation_order: int | None
    business_call_id: str | None
    effective_chapter_id: int | None
    entity_id: str | None
    relation_id: str | None
    participant_id: str | None
    declaration_id: str | None
    description_action: str | None
    description_value: str | None
    representative_action: str | None
    representative_value: bool | None
    tags_submitted: bool | None
    relation_change_kind: str | None
    identity_kind: str | None
    reason: str | None
    plotline_subject_id: str | None
    plotline_subject_title: str | None
    plotline_description: str | None
    plotline_before: str | None
    plotline_after: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FactEntityTagRecord:
    "FactEntityTag 的持久化事实快照"

    id: str
    graph_fact_id: str
    tag_ordinal: int
    tag: str


@dataclass(frozen=True, slots=True)
class LinguisticSpanRecord:
    "LinguisticSpan 的持久化事实快照"

    span_id: str
    run_id: str
    paragraph_id: int
    start_char: int
    end_char: int
    token_index: int | None
    raw_pos: str | None
    raw_entity_type: str | None
    phrase_match_kind: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LinguisticArcRecord:
    "LinguisticArc 的持久化事实快照"

    arc_id: str
    dependent_span_id: str
    head_span_id: str | None
    relation_code: str
    source_ordinal: int


@dataclass(frozen=True, slots=True)
class NovelRecord:
    "Novel 的持久化事实快照"

    novel_id: str
    filename: str | None
    file_path: str | None
    title: str | None
    author: str | None
    file_size: int | None
    upload_time: datetime | None


@dataclass(frozen=True, slots=True)
class NarrativeLinkRecord:
    "NarrativeLink 的持久化事实快照"

    link_id: str
    producer_execution_id: str
    reason: str
    semantic_source_event_id: str | None
    semantic_source_declaration_id: str | None
    semantic_target_event_id: str | None
    semantic_target_declaration_id: str | None
    relation_type: str | None
    source_operation_local_key: str | None
    annotation_local_key: str | None
    created_at: datetime | None
    is_active: bool | None
    expired_at: datetime | None
    cause_role: str | None
    contained_child_id: str | None
    contained_parent_id: str | None
    member_event_id: str | None
    arc_group_id: str | None
    outcome_group_id: str | None
    arc_role: str | None


@dataclass(frozen=True, slots=True)
class NarrativeGroupRecord:
    "NarrativeGroup 的持久化事实快照"

    group_id: str
    producer_execution_id: str
    title: str
    arc_kind: str | None
    arc_objective: str | None
    arc_role: str | None
    arc_reason: str | None
    parent_arc_id: str | None
    outcome_description: str | None


@dataclass(frozen=True, slots=True)
class OrganizationCheckRecord:
    "OrganizationCheck 的持久化事实快照"

    check_id: str
    producer_execution_id: str
    reason: str
    reviewed_event_id: str | None
    reviewed_declaration_id: str | None
    source_declaration_id: str | None
    target_declaration_id: str | None
    source_event_id: str | None
    target_event_id: str | None
    snapshot_hash: str | None
    disposition: str | None


@dataclass(frozen=True, slots=True)
class ConflictRecordRecord:
    "ConflictRecord 的持久化事实快照"

    conflict_id: str
    producer_execution_id: str
    reason: str
    subject_event_id: str | None
    subject_declaration_id: str | None
    subject_fact_id: str | None


@dataclass(frozen=True, slots=True)
class ConflictClaimRecord:
    "ConflictClaim 的持久化事实快照"

    claim_id: str
    conflict_id: str
    claim_ordinal: int
    producer_execution_id: str
    claim_text: str


@dataclass(frozen=True, slots=True)
class EventForeshadowingActionRecord:
    "EventForeshadowingAction 的持久化事实快照"

    action_id: str
    producer_execution_id: str
    source_operation_local_key: str
    operation_order: int
    action_type: str
    source_declaration_id: str
    target_declaration_id: str | None


@dataclass(frozen=True, slots=True)
class SourceEvidenceRecord:
    "SourceEvidence 的持久化事实快照"

    evidence_id: str
    ordinal: int
    paragraph_id: int
    start_char: int
    end_char: int
    related_complete_event_id: str | None
    graph_fact_id: str | None
    declaration_id: str | None
    complete_event_id: str | None
    narrative_group_id: str | None
    narrative_link_id: str | None
    foreshadow_action_id: str | None
    conflict_id: str | None
    claim_id: str | None
    check_id: str | None


@dataclass(frozen=True, slots=True)
class ParagraphRecord:
    "Paragraph 的持久化事实快照"

    id: str
    run_id: str
    paragraph_id: int
    chapter_id: int
    paragraph_index: int
    source_paragraph_index: int
    fragment_index: int
    local_start_char: int
    text: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ParagraphFeatureRecord:
    "ParagraphFeature 的持久化事实快照"

    id: str
    run_id: str
    paragraph_id: int
    feature_code: str
    vector_value: list[float] | None
    scalar_value: float | None
    count_value: int | None
    in_vocabulary_token_count: int | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ParagraphMetricRecord:
    "ParagraphMetric 的持久化事实快照"

    id: str
    run_id: str
    paragraph_id: int
    token_count: int | None
    sentence_count: int | None
    sentence_char_sum: float | None
    sentence_char_sum_sq: float | None
    positive_weight_sum: float | None
    negative_weight_sum: float | None
    fight_weight_sum: float | None
    exclaim_count: int | None
    question_count: int | None
    pause_count: int | None
    dialogue_char_count: int | None
    sensory_hit_count: int | None
    imagery_hit_count: int | None
    metaphor_sentence_count: int | None
    body_reaction_hit_count: int | None
    metrics_created_at: datetime | None
    preprocess_observed_at: datetime | None
    linguistic_completed_at: datetime | None
    phrase_completed_at: datetime | None
    fw_之: int | None
    fw_其: int | None
    fw_者: int | None
    fw_也: int | None
    fw_所: int | None
    fw_以: int | None
    fw_而: int | None
    fw_与: int | None
    fw_则: int | None
    fw_乃: int | None
    fw_于: int | None
    fw_乎: int | None
    fw_矣: int | None
    fw_焉: int | None
    fw_哉: int | None
    fw_兮: int | None
    fw_尔: int | None
    fw_若: int | None
    fw_为: int | None
    fw_何: int | None
    semantic_combat: int | None
    semantic_body: int | None
    semantic_relation: int | None
    semantic_faction: int | None
    semantic_command: int | None
    semantic_action: int | None
    semantic_psychology: int | None
    semantic_measure: int | None
    semantic_emotion: int | None
    semantic_color: int | None
    boundary_pos_score_sum: float | None
    boundary_neg_score_sum: float | None
    inference_token_count: int | None
    inference_status: str | None
    inference_error_text: str | None
    inference_created_at: datetime | None


@dataclass(frozen=True, slots=True)
class ParagraphTopicRecord:
    "ParagraphTopic 的持久化事实快照"

    id: str
    run_id: str
    paragraph_id: int
    topic_id: int
    topic_weight: float


@dataclass(frozen=True, slots=True)
class WorkItemRecord:
    "WorkItem 的持久化事实快照"

    work_id: str
    role: str | None
    annotation_run_id: str | None
    annotation_chapter_id: int | None
    diagnosis_session_id: str | None
    program_run_id: str | None
    program_chapter_id: int | None
    program_code: str | None
    program_invocation_key: str | None


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    "Execution 的持久化事实快照"

    execution_id: str
    session_run_id: str | None
    session_created_at: datetime | None
    run_id: str | None
    role: str | None
    chapter_id: int | None
    case_anchor: str | None
    work_id: str | None
    attempt_number: int | None
    started_at: datetime | None
    finished_at: datetime | None
    status: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class ChapterAnnotationRecord:
    "ChapterAnnotation 的持久化事实快照"

    record_id: str
    execution_id: str
    run_id: str
    chapter_id: int
    role: str
    contract_version: str
    chapter_consolidation_version: str
    summary: str | None
    emotional_valence: int | None
    narrative_function: str | None
    pivot_moment: bool | None
    cliffhanger: bool | None
    created_at: datetime
    saved_at: datetime


@dataclass(frozen=True, slots=True)
class DiagnosisReportRecord:
    "DiagnosisReport 的持久化事实快照"

    report_id: str
    session_id: str
    contract_version: str
    diagnosis: str | None
    value_logic_type: str | None
    value_logic_reason: str | None
    power_stance_score: int | None
    power_stance_reason: str | None
    common_people_dignity: int | None
    dignity_reason: str | None
    cultural_depth_score: int | None
    cultural_depth_reason: str | None
    narrative_arc_type: str | None
    focus_structure: str | None
    theme_color: str | None
    identity_snapshot: str | None
    structure_snapshot: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AnalysisAssessmentRecord:
    "AnalysisAssessment 的持久化事实快照"

    assessment_id: str
    record_id: str | None
    report_id: str | None
    paragraph_id: int | None
    emotion: int | None
    ordinal: int | None
    genre_label: str | None
    style_label: str | None
    topic_id: int | None
    topic_label: str | None
    scored_entity_id: str | None
    character_score: float | None
    cast_role: str | None
    cast_entity_id: str | None
