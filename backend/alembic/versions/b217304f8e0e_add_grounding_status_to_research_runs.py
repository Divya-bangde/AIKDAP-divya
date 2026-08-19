"""add grounding_status to research_runs

Sprint 9E: how well a run's answer is supported by its cited evidence.

A column rather than a key inside the existing `citations` JSONB: this
is a property of the run, not of any one citation, and it has to be
queryable ("which runs could not be answered from the knowledge base?"),
which a value buried in a JSONB array is not.

Nullable, with no backfill. Runs that completed before this sprint were
produced by the extractive synthesizer and were never assessed for
grounding; writing a value for them would be inventing a verdict after
the fact. NULL means "not assessed", which is the truth.

Unlike `create_table`, `add_column` does not create the enum type
implicitly, so it is created explicitly on the way up and dropped on
the way down — matching `f3d098d397cc`, and without which a downgrade
followed by an upgrade fails with "type already exists".

Revision ID: b217304f8e0e
Revises: a2596498377b
Create Date: 2026-08-16 14:21:42.472002+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b217304f8e0e'
down_revision: Union[str, None] = 'a2596498377b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GROUNDING_STATUS_ENUM = 'research_grounding_status_enum'
GROUNDING_STATUS_VALUES = (
    'grounded',
    'partially_grounded',
    'insufficient_evidence',
    'failed',
)


def upgrade() -> None:
    bind = op.get_bind()
    grounding_status = postgresql.ENUM(
        *GROUNDING_STATUS_VALUES, name=GROUNDING_STATUS_ENUM
    )
    grounding_status.create(bind, checkfirst=True)

    op.add_column(
        'research_runs',
        sa.Column(
            'grounding_status',
            sa.Enum(*GROUNDING_STATUS_VALUES, name=GROUNDING_STATUS_ENUM),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('research_runs', 'grounding_status')

    bind = op.get_bind()
    postgresql.ENUM(name=GROUNDING_STATUS_ENUM).drop(bind, checkfirst=True)
