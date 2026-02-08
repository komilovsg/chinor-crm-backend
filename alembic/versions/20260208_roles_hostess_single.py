"""roles: hostess_1, hostess_2 -> hostess

Revision ID: 20260208_hostess
Revises: 20260208_exclude_bc
Create Date: 2026-02-08

"""
from collections.abc import Sequence

from alembic import op

revision: str = "20260208_hostess"
down_revision: str | None = "20260208_exclude_bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE users SET role = 'hostess'
        WHERE role IN ('hostess_1', 'hostess_2')
    """)


def downgrade() -> None:
    # Обратно не переводим: непонятно, кто был hostess_1, кто hostess_2
    pass
