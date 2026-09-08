"""add unsourced grounding status

Sprint 16 Phase 8.13. Adds `unsourced` to `research_grounding_status_enum`
for the new opt-in "answer from general knowledge" path
(`UnsourcedSynthesizer`): a run that deliberately answers outside the
evidence boundary, on an explicit user action, always with zero
citations. Autogenerate does not detect enum member changes (the same
limitation already noted in `fae4f91a412b`), so this is hand-written --
one `ADD VALUE`, same pattern as that migration.

`ALTER TYPE ... ADD VALUE` is safe inside Alembic's normal transactional
migration on Postgres 12+ (this project runs 17) as long as the new
value is only added, never referenced, within the same transaction --
which this migration does not do.

Revision ID: d8017a854183
Revises: 3abf531e2215
Create Date: 2026-09-08 06:30:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8017a854183'
down_revision: Union[str, None] = '3abf531e2215'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE research_grounding_status_enum ADD VALUE IF NOT EXISTS 'unsourced'")


def downgrade() -> None:
    # Postgres has no `ALTER TYPE ... DROP VALUE` -- removing an enum
    # value requires rebuilding the type, which is unsafe to do
    # automatically without knowing whether any row still uses it.
    # Nothing else in this migration to reverse.
    pass
