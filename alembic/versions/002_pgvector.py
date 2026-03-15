"""Add pgvector support for embeddings

Revision ID: 002_pgvector
Revises: 001_initial
Create Date: 2026-03-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_pgvector'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Embedding dimension (OpenAI text-embedding-3-small uses 1536)
EMBEDDING_DIM = 1536


def upgrade() -> None:
    # Add embedding_vector column to chunk_embeddings table
    op.execute(f"""
        ALTER TABLE chunk_embeddings 
        ADD COLUMN IF NOT EXISTS embedding_vector vector({EMBEDDING_DIM})
    """)
    
    # Add embedding_vector column to entities table
    op.execute(f"""
        ALTER TABLE entities 
        ADD COLUMN IF NOT EXISTS embedding_vector vector({EMBEDDING_DIM})
    """)
    
    # Create HNSW indexes for vector similarity search
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_vector 
        ON chunk_embeddings 
        USING hnsw (embedding_vector vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_entities_vector 
        ON entities 
        USING hnsw (embedding_vector vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_entities_vector")
    op.execute("DROP INDEX IF EXISTS idx_chunk_embeddings_vector")
    op.execute("ALTER TABLE entities DROP COLUMN IF EXISTS embedding_vector")
    op.execute("ALTER TABLE chunk_embeddings DROP COLUMN IF EXISTS embedding_vector")
