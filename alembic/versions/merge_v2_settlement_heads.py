"""Merge Builder V2 and settlement/history migration heads."""

revision = "merge_v2_settlement_heads"
down_revision = (
    "add_builder_run_request_context",
    "add_canonical_fixture_identity",
    "add_tier_booking_editions",
)
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
