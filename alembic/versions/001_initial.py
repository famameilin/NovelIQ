"""Initial migration - create all tables

Revision ID: 001_initial
Revises: 
Create Date: 2026-03-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # analysis_runs table
    op.create_table(
        'analysis_runs',
        sa.Column('run_id', sa.String(36), primary_key=True),
        sa.Column('novel_id', sa.String(255), nullable=False),
        sa.Column('source_path', sa.Text, nullable=True),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime, nullable=True),
        sa.Column('updated_at', sa.DateTime, nullable=True),
    )
    op.create_index('idx_analysis_runs_novel', 'analysis_runs', ['novel_id'])
    op.create_index('idx_analysis_runs_status', 'analysis_runs', ['status'])

    # chunks table
    op.create_table(
        'chunks',
        sa.Column('chunk_id', sa.Integer, primary_key=True),
        sa.Column('chapter_id', sa.Integer, nullable=True),
        sa.Column('char_offset', sa.Integer, nullable=True),
        sa.Column('text', sa.Text, nullable=False),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_chunks_run_id', 'chunks', ['run_id'])

    # chunk_style table
    op.create_table(
        'chunk_style',
        sa.Column('chunk_id', sa.Integer, sa.ForeignKey('chunks.chunk_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mtld', sa.Float, nullable=True),
        sa.Column('ttr', sa.Float, nullable=True),
        sa.Column('avg_sent_len', sa.Float, nullable=True),
        sa.Column('sent_len_std', sa.Float, nullable=True),
        sa.Column('d_value', sa.Float, nullable=True),
        sa.Column('pause_density', sa.Float, nullable=True),
        sa.Column('fight_density', sa.Float, nullable=True),
        sa.Column('exclaim_density', sa.Float, nullable=True),
        sa.Column('dialogue_ratio', sa.Float, nullable=True),
        sa.Column('question_density', sa.Float, nullable=True),
        sa.Column('sensory_density', sa.Float, nullable=True),
        sa.Column('metaphor_density', sa.Float, nullable=True),
        sa.Column('cultural_density', sa.Float, nullable=True),
        sa.Column('function_word_vector', sa.Text, nullable=True),
        sa.Column('category_density_combat', sa.Float, nullable=True),
        sa.Column('category_density_body', sa.Float, nullable=True),
        sa.Column('category_density_relation', sa.Float, nullable=True),
        sa.Column('category_density_faction', sa.Float, nullable=True),
        sa.Column('category_density_command', sa.Float, nullable=True),
        sa.Column('category_density_action', sa.Float, nullable=True),
        sa.Column('category_density_psychology', sa.Float, nullable=True),
        sa.Column('category_density_measure', sa.Float, nullable=True),
        sa.Column('category_density_emotion', sa.Float, nullable=True),
        sa.Column('category_density_color', sa.Float, nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_chunk_style_run_id', 'chunk_style', ['run_id'])

    # chunk_culture table
    op.create_table(
        'chunk_culture',
        sa.Column('chunk_id', sa.Integer, sa.ForeignKey('chunks.chunk_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('confucian_density', sa.Float, nullable=True),
        sa.Column('taoist_density', sa.Float, nullable=True),
        sa.Column('buddhist_density', sa.Float, nullable=True),
        sa.Column('folk_density', sa.Float, nullable=True),
        sa.Column('allusion_density', sa.Float, nullable=True),
        sa.Column('imagery_density', sa.Float, nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_chunk_culture_run_id', 'chunk_culture', ['run_id'])

    # chunk_topics table
    op.create_table(
        'chunk_topics',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('chunk_id', sa.Integer, sa.ForeignKey('chunks.chunk_id', ondelete='CASCADE'), nullable=False),
        sa.Column('topic_id', sa.Integer, nullable=False),
        sa.Column('topic_weight', sa.Float, nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_chunk_topics_chunk_id', 'chunk_topics', ['chunk_id'])
    op.create_index('idx_chunk_topics_topic_id', 'chunk_topics', ['topic_id'])
    op.create_index('idx_chunk_topics_run_id', 'chunk_topics', ['run_id'])

    # chunk_embeddings table
    op.create_table(
        'chunk_embeddings',
        sa.Column('chunk_id', sa.Integer, sa.ForeignKey('chunks.chunk_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('embedding', sa.LargeBinary, nullable=True),
        sa.Column('created_at', sa.String(50), nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_chunk_embeddings_run_id', 'chunk_embeddings', ['run_id'])

    # chunk_annotation table
    op.create_table(
        'chunk_annotation',
        sa.Column('chunk_id', sa.Integer, sa.ForeignKey('chunks.chunk_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('emotional_valence', sa.String(50), nullable=True),
        sa.Column('pivot_moment', sa.Integer, nullable=True),
        sa.Column('event_type', sa.String(50), nullable=True),
        sa.Column('cliffhanger', sa.Integer, nullable=True),
        sa.Column('has_foreshadowing', sa.Integer, nullable=True),
        sa.Column('foreshadowing_type', sa.String(50), nullable=True),
        sa.Column('foreshadowing_desc', sa.Text, nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_chunk_annotation_run_id', 'chunk_annotation', ['run_id'])

    # chunk_characters table
    op.create_table(
        'chunk_characters',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('chunk_id', sa.Integer, sa.ForeignKey('chunks.chunk_id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('role_function', sa.String(50), nullable=True),
        sa.Column('action', sa.Text, nullable=True),
        sa.Column('action_type', sa.String(50), nullable=True),
        sa.Column('emotion_score', sa.String(50), nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_chunk_characters_chunk_id', 'chunk_characters', ['chunk_id'])
    op.create_index('idx_chunk_characters_name', 'chunk_characters', ['name'])
    op.create_index('idx_chunk_characters_run_id', 'chunk_characters', ['run_id'])

    # chunk_relations table
    op.create_table(
        'chunk_relations',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('chunk_id', sa.Integer, sa.ForeignKey('chunks.chunk_id', ondelete='CASCADE'), nullable=False),
        sa.Column('from_char', sa.String(255), nullable=True),
        sa.Column('to_char', sa.String(255), nullable=True),
        sa.Column('type', sa.String(50), nullable=True),
        sa.Column('change', sa.String(50), nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_chunk_relations_chunk_id', 'chunk_relations', ['chunk_id'])
    op.create_index('idx_chunk_relations_run_id', 'chunk_relations', ['run_id'])

    # chunk_dialogues table
    op.create_table(
        'chunk_dialogues',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('chunk_id', sa.Integer, sa.ForeignKey('chunks.chunk_id', ondelete='CASCADE'), nullable=False),
        sa.Column('speaker', sa.String(255), nullable=True),
        sa.Column('length', sa.Integer, nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_chunk_dialogues_chunk_id', 'chunk_dialogues', ['chunk_id'])
    op.create_index('idx_chunk_dialogues_run_id', 'chunk_dialogues', ['run_id'])

    # chunk_foreshadowing table
    op.create_table(
        'chunk_foreshadowing',
        sa.Column('chunk_id', sa.Integer, sa.ForeignKey('chunks.chunk_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('foreshadowing_type', sa.String(50), nullable=True),
        sa.Column('anchor_text', sa.Text, nullable=True),
        sa.Column('anchor_reason', sa.Text, nullable=True),
        sa.Column('confidence', sa.String(20), nullable=True),
        sa.Column('created_at', sa.String(50), nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_chunk_foreshadowing_run_id', 'chunk_foreshadowing', ['run_id'])

    # character_appearances table
    op.create_table(
        'character_appearances',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('chunk_id', sa.Integer, sa.ForeignKey('chunks.chunk_id', ondelete='CASCADE'), nullable=False),
        sa.Column('raw_name', sa.String(255), nullable=True),
        sa.Column('identity_clue', sa.Text, nullable=True),
        sa.Column('clue_type', sa.String(50), nullable=True),
        sa.Column('created_at', sa.String(50), nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_character_appearances_chunk_id', 'character_appearances', ['chunk_id'])
    op.create_index('idx_character_appearances_raw_name', 'character_appearances', ['raw_name'])
    op.create_index('idx_character_appearances_run_id', 'character_appearances', ['run_id'])

    # entities table
    op.create_table(
        'entities',
        sa.Column('entity_id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('novel_id', sa.String(255), nullable=False),
        sa.Column('canonical', sa.String(255), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('first_chunk', sa.Integer, nullable=True),
        sa.Column('last_chunk', sa.Integer, nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('embedding', sa.LargeBinary, nullable=True),
        sa.Column('confidence', sa.Float, nullable=False, server_default='1.0'),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
        sa.UniqueConstraint('novel_id', 'canonical', name='uq_entities_novel_canonical'),
    )
    op.create_index('idx_entities_novel_id', 'entities', ['novel_id'])
    op.create_index('idx_entities_run_id', 'entities', ['run_id'])

    # entity_aliases table
    op.create_table(
        'entity_aliases',
        sa.Column('alias_id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('entity_id', sa.Integer, sa.ForeignKey('entities.entity_id', ondelete='CASCADE'), nullable=False),
        sa.Column('alias', sa.String(255), nullable=False),
        sa.Column('alias_type', sa.String(50), nullable=True),
        sa.Column('source_chunk', sa.Integer, nullable=True),
        sa.Column('confirm_count', sa.Integer, nullable=False, server_default='1'),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
        sa.UniqueConstraint('entity_id', 'alias', name='uq_entity_aliases_entity_alias'),
    )
    op.create_index('idx_entity_aliases_alias', 'entity_aliases', ['alias'])
    op.create_index('idx_entity_aliases_run_id', 'entity_aliases', ['run_id'])

    # entity_relations table
    op.create_table(
        'entity_relations',
        sa.Column('rel_id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('novel_id', sa.String(255), nullable=False),
        sa.Column('from_entity', sa.Integer, sa.ForeignKey('entities.entity_id', ondelete='CASCADE'), nullable=False),
        sa.Column('to_entity', sa.Integer, sa.ForeignKey('entities.entity_id', ondelete='CASCADE'), nullable=False),
        sa.Column('rel_type', sa.String(50), nullable=False),
        sa.Column('first_chunk', sa.Integer, nullable=True),
        sa.Column('last_chunk', sa.Integer, nullable=True),
        sa.Column('tension', sa.Float, nullable=False, server_default='0.0'),
        sa.Column('is_active', sa.Integer, nullable=False, server_default='1'),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
        sa.UniqueConstraint('novel_id', 'from_entity', 'to_entity', 'rel_type', name='uq_entity_relations'),
    )
    op.create_index('idx_entity_relations_novel_id', 'entity_relations', ['novel_id'])
    op.create_index('idx_entity_relations_run_id', 'entity_relations', ['run_id'])

    # entity_snapshots table
    op.create_table(
        'entity_snapshots',
        sa.Column('snap_id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('novel_id', sa.String(255), nullable=False),
        sa.Column('entity_id', sa.Integer, sa.ForeignKey('entities.entity_id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_id', sa.Integer, nullable=False),
        sa.Column('state_json', sa.Text, nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
        sa.UniqueConstraint('novel_id', 'entity_id', 'chunk_id', name='uq_entity_snapshots'),
    )
    op.create_index('idx_entity_snapshots_novel_chunk', 'entity_snapshots', ['novel_id', 'chunk_id'])
    op.create_index('idx_entity_snapshots_run_id', 'entity_snapshots', ['run_id'])

    # entity_registry table
    op.create_table(
        'entity_registry',
        sa.Column('entity_id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('chunk_id', sa.Integer, sa.ForeignKey('chunks.chunk_id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('role', sa.String(50), nullable=True),
        sa.Column('last_action', sa.Text, nullable=True),
        sa.Column('last_emotion', sa.String(50), nullable=True),
        sa.Column('emotion_score', sa.Integer, nullable=True),
        sa.Column('updated_at', sa.String(50), nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_entity_registry_chunk_id', 'entity_registry', ['chunk_id'])
    op.create_index('idx_entity_registry_run_id', 'entity_registry', ['run_id'])

    # cloud_analysis table
    op.create_table(
        'cloud_analysis',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('novel_id', sa.String(255), nullable=True),
        sa.Column('foreshadow_rate', sa.Float, nullable=True),
        sa.Column('arc_scores', sa.Text, nullable=True),
        sa.Column('narrative_type', sa.String(100), nullable=True),
        sa.Column('topic_labels', sa.Text, nullable=True),
        sa.Column('diagnosis', sa.Text, nullable=True),
        sa.Column('value_logic_type', sa.String(50), nullable=True),
        sa.Column('value_logic_reason', sa.Text, nullable=True),
        sa.Column('power_stance_score', sa.Integer, nullable=True),
        sa.Column('power_stance_reason', sa.Text, nullable=True),
        sa.Column('common_people_dignity', sa.Integer, nullable=True),
        sa.Column('dignity_reason', sa.Text, nullable=True),
        sa.Column('cultural_depth_score', sa.Integer, nullable=True),
        sa.Column('cultural_depth_reason', sa.Text, nullable=True),
        sa.Column('emotion_curve_type', sa.String(50), nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_cloud_analysis_novel_id', 'cloud_analysis', ['novel_id'])
    op.create_index('idx_cloud_analysis_run_id', 'cloud_analysis', ['run_id'])

    # emotion_curve table
    op.create_table(
        'emotion_curve',
        sa.Column('chunk_id', sa.Integer, sa.ForeignKey('chunks.chunk_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('pos_density', sa.Float, nullable=True),
        sa.Column('neg_density', sa.Float, nullable=True),
        sa.Column('net_density', sa.Float, nullable=True),
        sa.Column('smoothed_density', sa.Float, nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_emotion_curve_run_id', 'emotion_curve', ['run_id'])

    # rhythm_curve table
    op.create_table(
        'rhythm_curve',
        sa.Column('chunk_id', sa.Integer, sa.ForeignKey('chunks.chunk_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('tension_proxy', sa.Float, nullable=True),
        sa.Column('tension_composite', sa.Float, nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_rhythm_curve_run_id', 'rhythm_curve', ['run_id'])

    # global_stats table
    op.create_table(
        'global_stats',
        sa.Column('stat_name', sa.String(255), primary_key=True),
        sa.Column('stat_value', sa.Float, nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_global_stats_run_id', 'global_stats', ['run_id'])

    # global_context table
    op.create_table(
        'global_context',
        sa.Column('novel_id', sa.String(255), primary_key=True),
        sa.Column('novel_title', sa.String(500), nullable=True),
        sa.Column('core_characters', sa.Text, nullable=True),
        sa.Column('world_setting', sa.Text, nullable=True),
        sa.Column('updated_at', sa.String(50), nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_global_context_run_id', 'global_context', ['run_id'])

    # chunk_summaries table
    op.create_table(
        'chunk_summaries',
        sa.Column('chunk_id', sa.Integer, sa.ForeignKey('chunks.chunk_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('summary', sa.Text, nullable=True),
        sa.Column('created_at', sa.String(50), nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_chunk_summaries_run_id', 'chunk_summaries', ['run_id'])

    # token_usage table
    op.create_table(
        'token_usage',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('novel_id', sa.String(255), nullable=False),
        sa.Column('chunk_id', sa.Integer, nullable=True),
        sa.Column('task_type', sa.String(100), nullable=False),
        sa.Column('call_type', sa.String(50), nullable=False),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('prompt_tokens', sa.Integer, nullable=False),
        sa.Column('completion_tokens', sa.Integer, nullable=True),
        sa.Column('total_tokens', sa.Integer, nullable=False),
        sa.Column('created_at', sa.String(50), nullable=False),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
    )
    op.create_index('idx_token_usage_novel_id', 'token_usage', ['novel_id'])
    op.create_index('idx_token_usage_task_type', 'token_usage', ['novel_id', 'task_type'])
    op.create_index('idx_token_usage_run_id', 'token_usage', ['run_id'])

    # graph_storage table
    op.create_table(
        'graph_storage',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('graph_name', sa.String(255), nullable=False),
        sa.Column('graph_json', sa.Text, nullable=False),
        sa.Column('created_at', sa.String(50), nullable=True),
        sa.Column('updated_at', sa.String(50), nullable=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('analysis_runs.run_id', ondelete='CASCADE'), nullable=True),
        sa.UniqueConstraint('graph_name', 'run_id', name='uq_graph_storage_name_run'),
    )
    op.create_index('idx_graph_storage_run_id', 'graph_storage', ['run_id'])


def downgrade() -> None:
    op.drop_table('graph_storage')
    op.drop_table('token_usage')
    op.drop_table('chunk_summaries')
    op.drop_table('global_context')
    op.drop_table('global_stats')
    op.drop_table('rhythm_curve')
    op.drop_table('emotion_curve')
    op.drop_table('cloud_analysis')
    op.drop_table('entity_registry')
    op.drop_table('entity_snapshots')
    op.drop_table('entity_relations')
    op.drop_table('entity_aliases')
    op.drop_table('entities')
    op.drop_table('character_appearances')
    op.drop_table('chunk_foreshadowing')
    op.drop_table('chunk_dialogues')
    op.drop_table('chunk_relations')
    op.drop_table('chunk_characters')
    op.drop_table('chunk_annotation')
    op.drop_table('chunk_embeddings')
    op.drop_table('chunk_topics')
    op.drop_table('chunk_culture')
    op.drop_table('chunk_style')
    op.drop_table('chunks')
    op.drop_table('analysis_runs')
