"""Remove legacy embedding columns, keep only vector columns

Revision ID: 003_remove_legacy_embedding
Revises: 002_pgvector
Create Date: 2026-03-15

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '003_remove_legacy_embedding'
down_revision: Union[str, None] = '002_pgvector'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE chunk_embeddings DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE entities DROP COLUMN IF EXISTS embedding")


def downgrade() -> None:
    op.execute("ALTER TABLE entities ADD COLUMN embedding bytea")
    op.execute("ALTER TABLE chunk_embeddings ADD COLUMN embedding bytea")
