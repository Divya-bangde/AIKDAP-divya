"""add research follow-ups and visualization

Two nullable, additive columns on `research_runs` (existing rows need no
backfill):

- `parent_run_id` -- self-referencing FK for a follow-up question asked
  on a completed run. SET NULL on delete, matching `task_id`: removing a
  parent must not erase a follow-up's own audit trail.
- `visualization` -- JSONB chart/diagram spec that synthesis produces
  only when the question asks for one (see `schemas.Visualization`).

Revision ID: 5f3c9e1a7b24
Revises: d8017a854183
Create Date: 2026-09-10 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5f3c9e1a7b24'
down_revision: Union[str, None] = 'd8017a854183'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('research_runs', sa.Column('parent_run_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f('fk_research_runs_parent_run_id_research_runs'),
        'research_runs',
        'research_runs',
        ['parent_run_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        op.f('ix_research_runs_parent_run_id'), 'research_runs', ['parent_run_id'], unique=False
    )
    op.add_column(
        'research_runs',
        sa.Column('visualization', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('research_runs', 'visualization')
    op.drop_index(op.f('ix_research_runs_parent_run_id'), table_name='research_runs')
    op.drop_constraint(
        op.f('fk_research_runs_parent_run_id_research_runs'), 'research_runs', type_='foreignkey'
    )
    op.drop_column('research_runs', 'parent_run_id')
