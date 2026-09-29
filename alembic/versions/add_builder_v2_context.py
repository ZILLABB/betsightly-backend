"""Preserve V2 mode/provenance without inventing target odds.

Existing historical rows keep their values and default to target_odds mode.
Downgrade deliberately retains this additive schema: dropping provenance or
making targets mandatory again would destroy or invalidate V2 history.
"""
from alembic import op
import sqlalchemy as sa

revision = "add_builder_v2_context"
down_revision = "add_tier_recovery_provenance"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("builder_predictions"):
        # This table historically came from runtime create_all rather than
        # Alembic. Freeze its complete schema here for fresh installations.
        op.create_table(
            "builder_predictions",
            sa.Column("selection_fingerprint", sa.String(64), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("target_odds", sa.Float(), nullable=True),
            sa.Column("horizon", sa.String(16), nullable=False),
            sa.Column("generated_odds", sa.Float(), nullable=False),
            sa.Column("actual_sportybet_odds", sa.Float()),
            sa.Column("leg_count", sa.Integer(), nullable=False),
            sa.Column("picks", sa.Text(), nullable=False),
            *[sa.Column(name, sa.Float()) for name in (
                "hit_probability", "target_hit_probability", "no_loss_probability",
                "expected_return", "avg_confidence", "avg_evidence_probability",
                "minimum_trust_score", "actual_settled_return", "sportybet_settled_return", "profit",
            )],
            sa.Column("policy_version", sa.String(40)),
            sa.Column("booking_status", sa.String(32)),
            sa.Column("validation_status", sa.String(32)),
            sa.Column("final_status", sa.String(20), nullable=False),
            sa.Column("all_win", sa.Boolean()),
            sa.Column("target_reached", sa.Boolean()),
            sa.Column("settled_at", sa.DateTime(timezone=True)),
        )
    for table in ("builder_runs", "builder_predictions"):
        columns = {c["name"]: c for c in sa.inspect(bind).get_columns(table)}
        with op.batch_alter_table(table) as batch:
            if "mode" not in columns:
                batch.add_column(sa.Column("mode", sa.String(24), nullable=False,
                                           server_default="target_odds"))
            if not columns["target_odds"]["nullable"]:
                batch.alter_column("target_odds", existing_type=sa.Float(), nullable=True)
            if table == "builder_predictions" and "board_context" not in columns:
                batch.add_column(sa.Column("board_context", sa.Text()))


def downgrade():
    # Data-preserving rollback: old target-only code tolerates extra columns.
    # Do not run old analytics over new non-target rows; use engine rollback
    # on this release instead of rolling the application binary back.
    pass
