"""Add analytics provider cache and Builder fact tables.

Revision ID: add_analytics_provider_tables
Revises: add_training_cache_tables
"""

from alembic import op
import sqlalchemy as sa

revision = "add_analytics_provider_tables"
down_revision = "add_training_cache_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "builder_runs",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_odds", sa.Float(), nullable=False),
        sa.Column("horizon", sa.String(16), nullable=False),
        sa.Column("refresh", sa.Boolean(), nullable=False),
        sa.Column("result_status", sa.String(24), nullable=False),
        sa.Column("leg_count", sa.Integer()),
        sa.Column("generated_odds", sa.Float()),
        sa.Column("ticket_produced", sa.Boolean(), nullable=False),
        sa.Column("booking_status", sa.String(32)),
        sa.Column("actual_sportybet_odds", sa.Float()),
        sa.Column("validation_status", sa.String(32)),
        sa.Column("failure_category", sa.String(64)),
        sa.Column("booking_variant_id", sa.String(64)),
        sa.Column("cached", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_builder_runs_requested_at", "builder_runs", ["requested_at"])
    op.create_table(
        "analytics_provider_cache",
        sa.Column("cache_key", sa.String(160), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("analytics_provider_cache")
    op.drop_index("ix_builder_runs_requested_at", table_name="builder_runs")
    op.drop_table("builder_runs")
