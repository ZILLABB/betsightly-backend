"""Append-only live booking editions; official published slips are untouched.

Revision ID: add_tier_booking_editions
Revises: add_shared_history_artifacts
"""
from alembic import op
import sqlalchemy as sa

revision = "add_tier_booking_editions"
down_revision = "add_shared_history_artifacts"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("tier_booking_editions"):
        return
    op.create_table(
        "tier_booking_editions",
        sa.Column("publish_date", sa.String(10), nullable=False),
        sa.Column("tier", sa.String(24), nullable=False),
        sa.Column("booking_version", sa.Integer(), nullable=False),
        sa.Column("previous_booking_version", sa.Integer()),
        sa.Column("official_card_id", sa.String(64), nullable=False),
        sa.Column("identity_hash", sa.String(64), nullable=False),
        sa.Column("generated_at", sa.String(32), nullable=False),
        sa.Column("checked_at", sa.String(32)),
        sa.Column("share_code", sa.String(32)),
        sa.Column("actual_sportybet_odds", sa.Float()),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("publish_date", "tier", "booking_version"),
    )


def downgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("tier_booking_editions"):
        op.drop_table("tier_booking_editions")
