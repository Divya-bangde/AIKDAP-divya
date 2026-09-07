"""add provenance columns and ocr_required status

Sprint 12.1. Two unrelated-looking but co-located changes: the new
`knowledge_chunks` provenance columns (page_number/sheet_name/section)
autogenerate detected on its own, and the new `ocr_required` value on
the existing `asset_processing_status_enum` Postgres enum, which
autogenerate does NOT detect (a well-known Alembic limitation --
it diffs table/column shape, not enum member sets) and had to be added
here by hand.

`ALTER TYPE ... ADD VALUE` is safe inside Alembic's normal
transactional migration on Postgres 12+ (this project runs 17) as long
as the new value is only added, never referenced, within the same
transaction -- which this migration does not do.

Revision ID: fae4f91a412b
Revises: b217304f8e0e
Create Date: 2026-08-24 12:01:21.744482+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fae4f91a412b'
down_revision: Union[str, None] = 'b217304f8e0e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('knowledge_chunks', sa.Column('page_number', sa.Integer(), nullable=True))
    op.add_column('knowledge_chunks', sa.Column('sheet_name', sa.String(length=255), nullable=True))
    op.add_column('knowledge_chunks', sa.Column('section', sa.String(length=500), nullable=True))
    op.execute("ALTER TYPE asset_processing_status_enum ADD VALUE IF NOT EXISTS 'ocr_required'")


def downgrade() -> None:
    # Postgres has no `ALTER TYPE ... DROP VALUE` -- removing an enum
    # value requires rebuilding the type, which is unsafe to do
    # automatically without knowing whether any row still uses it.
    # Column removal alone is fully reversible and is all this does.
    op.drop_column('knowledge_chunks', 'section')
    op.drop_column('knowledge_chunks', 'sheet_name')
    op.drop_column('knowledge_chunks', 'page_number')
