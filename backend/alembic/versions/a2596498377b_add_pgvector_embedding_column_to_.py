"""add pgvector embedding column to knowledge chunks

Sprint 9C: replaces the JSONB `embedding_vector` placeholder (Sprint 6)
with a native pgvector `embedding` column, dimension 1024 -- verified
live against this deployment's BGE-M3 model
(`litellm.aembedding(model="ollama/bge-m3", ...)` returned exactly
1024 floats) rather than assumed from BGE-M3's typical dimension.

Safe to replace rather than add alongside: confirmed via
`SELECT count(embedding_vector) FROM knowledge_chunks` returning 0
across every row in this environment before writing this migration --
no real embedding was ever generated against the old column (Sprint
6-9B intentionally left the embedding provider a placeholder).

`CREATE EXTENSION IF NOT EXISTS vector` runs explicitly here rather
than being assumed from the `pgvector/pgvector` Docker image alone:
the image only makes the extension available, not enabled.

Revision ID: a2596498377b
Revises: f3d098d397cc
Create Date: 2026-08-09 16:34:16.032416+00:00

"""
from typing import Sequence, Union

import pgvector.sqlalchemy
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a2596498377b'
down_revision: Union[str, None] = 'f3d098d397cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        'knowledge_chunks',
        sa.Column('embedding', pgvector.sqlalchemy.Vector(1024), nullable=True),
    )
    op.drop_column('knowledge_chunks', 'embedding_vector')


def downgrade() -> None:
    op.add_column(
        'knowledge_chunks',
        sa.Column('embedding_vector', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True),
    )
    op.drop_column('knowledge_chunks', 'embedding')
    # The extension is not dropped: doing so would fail loudly if any
    # other object in the database still depends on the `vector` type,
    # and (unlike the enum types other migrations in this project drop
    # on downgrade) there is no cheap, safe way to tell from here
    # whether that's the case. Leaving an unused extension enabled is
    # harmless; dropping one still in use is not.
