"""Persist safe Builder V2 request and selected-market provenance."""

from alembic import op
import sqlalchemy as sa

revision = "add_builder_run_request_context"
down_revision = "add_builder_v2_context"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("builder_runs")}
    with op.batch_alter_table("builder_runs") as batch:
        if "fill_strategy" not in columns:
            batch.add_column(sa.Column("fill_strategy", sa.String(48)))
        if "requested_markets" not in columns:
            batch.add_column(sa.Column("requested_markets", sa.Text()))
        if "selected_markets" not in columns:
            batch.add_column(sa.Column("selected_markets", sa.Text()))
        if "requested_game_count" not in columns:
            batch.add_column(sa.Column("requested_game_count", sa.Integer()))


def downgrade():
    # Retain append-only operational provenance on rollback.
    pass
