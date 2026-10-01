"""Add the shared, versioned history artifact and refresh lease row.

Revision ID: add_shared_history_artifacts
Revises: add_prediction_decision_archive

The primary key permits one authoritative artifact and one lease per cache key.
Downgrade removes only this new table and its cached history; it does not touch
published predictions or settlement. Run downgrade only after stopping readers.
"""

from alembic import op
import sqlalchemy as sa

revision = "add_shared_history_artifacts"
down_revision = "add_prediction_decision_archive"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "history_artifacts",
        sa.Column("cache_key", sa.String(120), primary_key=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text()),
        sa.Column("payload_sha256", sa.String(64)),
        sa.Column("built_at", sa.Float()),
        sa.Column("lease_owner", sa.String(36)),
        sa.Column("lease_until", sa.Float()),
        sa.CheckConstraint(
            "(payload IS NULL AND payload_sha256 IS NULL) OR "
            "(payload IS NOT NULL AND payload_sha256 IS NOT NULL)",
            name="ck_history_artifact_payload_digest_pair"),
    )


def downgrade():
    op.drop_table("history_artifacts")
