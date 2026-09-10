"""Add immutable prediction decision archive.

Revision ID: add_prediction_decision_archive
Revises: add_builder_revision_tables
"""
from alembic import op
import sqlalchemy as sa

revision = "add_prediction_decision_archive"
down_revision = "add_builder_revision_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "prediction_board_snapshots",
        sa.Column("snapshot_id", sa.String(64), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("publication_date", sa.String(10), nullable=False),
        sa.Column("coverage_start", sa.DateTime(timezone=True)),
        sa.Column("coverage_end", sa.DateTime(timezone=True)),
        sa.Column("requested_horizon", sa.Integer(), nullable=False),
        sa.Column("provider_state", sa.String(24), nullable=False),
        sa.Column("fixture_count", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("calibration_version", sa.String(64)),
        sa.Column("evidence_version", sa.String(64)),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("payload_bytes", sa.Integer(), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint("payload_sha256", "policy_version",
                            name="uq_board_payload_policy"),
    )
    op.create_index("ix_prediction_board_snapshots_publication_date",
                    "prediction_board_snapshots", ["publication_date"])
    op.create_table(
        "prediction_product_decisions",
        sa.Column("decision_id", sa.String(36), primary_key=True),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("publication_date", sa.String(10), nullable=False),
        sa.Column("product", sa.String(32), nullable=False),
        sa.Column("target_odds", sa.Float()),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("independent_payload", sa.Text(), nullable=False),
        sa.Column("final_payload", sa.Text(), nullable=False),
        sa.Column("diagnostics_payload", sa.Text(), nullable=False),
        sa.UniqueConstraint("snapshot_id", "publication_date", "product",
                            name="uq_product_snapshot_date"),
    )
    op.create_index("ix_prediction_product_decisions_snapshot_id",
                    "prediction_product_decisions", ["snapshot_id"])
    op.create_index("ix_prediction_product_decisions_publication_date",
                    "prediction_product_decisions", ["publication_date"])
    op.create_table(
        "builder_edit_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("snapshot_id", sa.String(64)),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("revision_before", sa.Integer()),
        sa.Column("revision_after", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("fixture_id", sa.String(128)),
        sa.Column("selection_id", sa.String(128)),
        sa.Column("replacement_selection_id", sa.String(128)),
        sa.Column("requested_target", sa.Float()),
        sa.Column("achieved_before", sa.Float()),
        sa.Column("achieved_after", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "request_id",
                            name="uq_builder_edit_request"),
    )
    op.create_index("ix_builder_edit_events_run_id", "builder_edit_events", ["run_id"])
    op.create_index("ix_builder_edit_events_snapshot_id", "builder_edit_events", ["snapshot_id"])


def downgrade():
    op.drop_table("builder_edit_events")
    op.drop_table("prediction_product_decisions")
    op.drop_table("prediction_board_snapshots")
