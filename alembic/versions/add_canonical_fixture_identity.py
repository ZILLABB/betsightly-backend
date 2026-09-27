"""Add canonical fixture identity and provider mappings.

Revision ID: add_canonical_fixture_identity
Revises: add_tier_recovery_provenance
"""
from alembic import op
import sqlalchemy as sa

revision = "add_canonical_fixture_identity"
down_revision = "add_tier_recovery_provenance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "canonical_teams",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("canonical_name", sa.String(180), nullable=False),
        sa.Column("normalized_name", sa.String(180), nullable=False),
        sa.Column("country", sa.String(80)),
        sa.Column("squad", sa.String(24), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_canonical_teams_normalized",
        "canonical_teams",
        ["normalized_name", "country", "squad"],
    )

    op.create_table(
        "canonical_competitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("canonical_name", sa.String(180), nullable=False),
        sa.Column("normalized_name", sa.String(180), nullable=False),
        sa.Column("country", sa.String(80)),
        sa.Column("competition_type", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_canonical_competitions_normalized",
        "canonical_competitions",
        ["normalized_name", "country"],
    )

    op.create_table(
        "canonical_fixtures",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("home_team_id", sa.String(36), nullable=False),
        sa.Column("away_team_id", sa.String(36), nullable=False),
        sa.Column("competition_id", sa.String(36)),
        sa.Column("kickoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="SCHEDULED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["home_team_id"], ["canonical_teams.id"]),
        sa.ForeignKeyConstraint(["away_team_id"], ["canonical_teams.id"]),
        sa.ForeignKeyConstraint(["competition_id"], ["canonical_competitions.id"]),
        sa.CheckConstraint(
            "home_team_id <> away_team_id",
            name="ck_canonical_fixture_distinct_teams",
        ),
    )
    op.create_index(
        "ix_canonical_fixtures_kickoff",
        "canonical_fixtures",
        ["kickoff"],
    )
    op.create_index(
        "ix_canonical_fixtures_teams_kickoff",
        "canonical_fixtures",
        ["home_team_id", "away_team_id", "kickoff"],
    )

    op.create_table(
        "provider_team_mappings",
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_team_id", sa.String(128), nullable=False),
        sa.Column("provider_name", sa.String(180), nullable=False),
        sa.Column("canonical_team_id", sa.String(36), nullable=False),
        sa.Column("match_method", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["canonical_team_id"], ["canonical_teams.id"]),
        sa.PrimaryKeyConstraint("provider", "provider_team_id"),
    )
    op.create_index(
        "ix_provider_team_mappings_canonical",
        "provider_team_mappings",
        ["canonical_team_id"],
    )

    op.create_table(
        "provider_competition_mappings",
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_competition_id", sa.String(128), nullable=False),
        sa.Column("provider_name", sa.String(180), nullable=False),
        sa.Column("canonical_competition_id", sa.String(36), nullable=False),
        sa.Column("match_method", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_competition_id"],
            ["canonical_competitions.id"],
        ),
        sa.PrimaryKeyConstraint("provider", "provider_competition_id"),
    )

    op.create_table(
        "provider_fixture_mappings",
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_fixture_id", sa.String(128), nullable=False),
        sa.Column("canonical_fixture_id", sa.String(36), nullable=False),
        sa.Column("match_method", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["canonical_fixture_id"], ["canonical_fixtures.id"]),
        sa.PrimaryKeyConstraint("provider", "provider_fixture_id"),
    )
    op.create_index(
        "ix_provider_fixture_mappings_canonical",
        "provider_fixture_mappings",
        ["canonical_fixture_id"],
    )

    op.create_table(
        "team_aliases",
        sa.Column("provider", sa.String(32), nullable=False, server_default="*"),
        sa.Column("normalized_alias", sa.String(180), nullable=False),
        sa.Column("canonical_team_id", sa.String(36), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["canonical_team_id"], ["canonical_teams.id"]),
        sa.PrimaryKeyConstraint("provider", "normalized_alias", "canonical_team_id"),
    )
    op.create_index(
        "ix_team_aliases_lookup",
        "team_aliases",
        ["provider", "normalized_alias"],
    )


def downgrade():
    op.drop_table("team_aliases")
    op.drop_table("provider_fixture_mappings")
    op.drop_table("provider_competition_mappings")
    op.drop_table("provider_team_mappings")
    op.drop_table("canonical_fixtures")
    op.drop_table("canonical_competitions")
    op.drop_table("canonical_teams")
