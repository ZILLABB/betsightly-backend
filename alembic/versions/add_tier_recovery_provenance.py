"""Add auditable provenance for transactional empty-tier recovery.

Revision ID: add_tier_recovery_provenance
Revises: add_prediction_decision_archive
"""

from alembic import op
import sqlalchemy as sa

revision = "add_tier_recovery_provenance"
down_revision = "add_prediction_decision_archive"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tier_recovery_provenance",
        sa.Column("publish_date", sa.String(10), nullable=False),
        sa.Column("tier", sa.String(24), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("snapshot_id", sa.String(64)),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("publish_date", "tier"),
    )


def downgrade():
    op.drop_table("tier_recovery_provenance")
