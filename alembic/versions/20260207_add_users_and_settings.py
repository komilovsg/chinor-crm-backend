"""add users and settings tables.

Revision ID: b3_users_settings
Revises:
Create Date: 2026-02-07

Создаёт таблицы users и settings только если их ещё нет. Существующие таблицы не пересоздаются.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import reflection

revision: str = "b3_users_settings"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(connection: sa.engine.Connection, name: str) -> bool:
    inspector = reflection.Inspector.from_engine(connection)
    return name in inspector.get_table_names()


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("role", sa.String(50), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email"),
        )
    if not _table_exists(conn, "settings"):
        op.create_table(
            "settings",
            sa.Column("key", sa.String(100), nullable=False),
            sa.Column("value", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("key"),
        )


def downgrade() -> None:
    op.drop_table("settings")
    op.drop_table("users")
