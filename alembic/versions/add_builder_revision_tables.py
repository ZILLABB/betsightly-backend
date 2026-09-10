"""Add immutable interactive Builder revision history.

Revision ID: add_builder_revision_tables
Revises: add_analytics_provider_tables
"""

from alembic import op
import sqlalchemy as sa

revision = "add_builder_revision_tables"
down_revision = "add_analytics_provider_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "builder_revision_runs",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("edit_token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_target", sa.Float(), nullable=False),
        sa.Column("horizon", sa.String(16), nullable=False),
        sa.Column("latest_revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "builder_revisions",
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("parent_revision", sa.Integer()),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("action_target", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("selected_fingerprint", sa.String(64)),
        sa.Column("locked_selection_ids", sa.Text(), nullable=False),
        sa.Column("excluded_fixture_ids", sa.Text(), nullable=False),
        sa.Column("excluded_selection_ids", sa.Text(), nullable=False),
        sa.Column("result_payload", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", "revision"),
        sa.UniqueConstraint("run_id", "request_id",
                            name="uq_builder_revision_request"),
    )
    op.create_table(
        "builder_revision_bookings",
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("selected_fingerprint", sa.String(64)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("booking_detail", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("run_id", "revision"),
    )


def downgrade():
    op.drop_table("builder_revision_bookings")
    op.drop_table("builder_revisions")
    op.drop_table("builder_revision_runs")
