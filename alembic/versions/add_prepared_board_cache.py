"""Add the persisted evaluated board cache without changing published history.

Revision ID: add_prepared_board_cache
Revises: add_user_ticket_history
"""

from alembic import op
import sqlalchemy as sa

revision = "add_prepared_board_cache"
down_revision = "add_user_ticket_history"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Earlier deployments may have created this optional cache at runtime.
    if inspector.has_table("prepared_board_cache"):
        return
    op.create_table(
        "prepared_board_cache",
        sa.Column("cache_key", sa.String(96), primary_key=True),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("slot", sa.String(16), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("payload_bytes", sa.Integer(), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
    )
    op.create_index(
        "ix_prepared_board_cache_horizon_days",
        "prepared_board_cache", ["horizon_days"],
    )


def downgrade():
    # Cached payloads may be the only immediately usable board after restart.
    # Keep the table so rollback does not remove the last known good snapshot.
    pass
