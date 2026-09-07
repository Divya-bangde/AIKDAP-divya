"""expand_execution_job_status_enum

Sprint 16 Phase 7B.11. Replaces `execution_job_status_enum`'s original
5-value set (`PENDING, LAUNCHED, SECURITY_BLOCKED, FAILED, COMPLETED` --
guessed ahead in Phase 7B.8, never actually written by any code path)
with the authoritative 9-value lifecycle: `PENDING, VALIDATING, LAUNCHING,
RUNNING, SUCCEEDED, FAILED, TIMED_OUT, CANCEL_REQUESTED, CANCELLED`. Only
`PENDING -> VALIDATING` is implemented as of this migration; the rest is
reserved for future Docker-launcher slices.

Three of the old names have no new equivalent (`LAUNCHED`/`SECURITY_BLOCKED`
folded into `RUNNING`/`FAILED` respectively, `COMPLETED` renamed to
`SUCCEEDED`), and Postgres has no `ALTER TYPE ... DROP VALUE` /
"rename value" operation -- shrinking or renaming a native enum's member
set requires rebuilding the type (rename old, create new, cast the
column across via `USING ... ::text::new_type`, drop old). Autogenerate
does not detect enum member changes at all (the same limitation already
noted in `fae4f91a412b`), so this is hand-written.

`execution_jobs` has no production usage: every row in it anywhere is
test-fixture data created by this development session's own test runs
(`ExecutionJobRepository.create()` is not yet called from any router or
Celery task). `TRUNCATE` before the type swap is therefore safe -- there
is no real data whose old status this migration would need to remap.

Revision ID: 452c53f7a4fe
Revises: 8f4f66de07a7
Create Date: 2026-09-03 17:57:07.483520+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '452c53f7a4fe'
down_revision: Union[str, None] = '8f4f66de07a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = (
    "PENDING", "VALIDATING", "LAUNCHING", "RUNNING", "SUCCEEDED",
    "FAILED", "TIMED_OUT", "CANCEL_REQUESTED", "CANCELLED",
)
_OLD_VALUES = ("PENDING", "LAUNCHED", "SECURITY_BLOCKED", "FAILED", "COMPLETED")


def upgrade() -> None:
    op.execute("TRUNCATE TABLE execution_jobs")
    op.execute("ALTER TYPE execution_job_status_enum RENAME TO execution_job_status_enum_old")
    op.execute(
        "CREATE TYPE execution_job_status_enum AS ENUM ("
        + ", ".join(f"'{v}'" for v in _NEW_VALUES)
        + ")"
    )
    op.execute(
        "ALTER TABLE execution_jobs ALTER COLUMN status TYPE execution_job_status_enum "
        "USING status::text::execution_job_status_enum"
    )
    op.execute("DROP TYPE execution_job_status_enum_old")


def downgrade() -> None:
    op.execute("TRUNCATE TABLE execution_jobs")
    op.execute("ALTER TYPE execution_job_status_enum RENAME TO execution_job_status_enum_new")
    op.execute(
        "CREATE TYPE execution_job_status_enum AS ENUM ("
        + ", ".join(f"'{v}'" for v in _OLD_VALUES)
        + ")"
    )
    op.execute(
        "ALTER TABLE execution_jobs ALTER COLUMN status TYPE execution_job_status_enum "
        "USING status::text::execution_job_status_enum"
    )
    op.execute("DROP TYPE execution_job_status_enum_new")
