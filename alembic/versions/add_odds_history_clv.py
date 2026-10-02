"""Add append-only odds observations and linked selection entry prices.

Revision ID: add_odds_history_clv
Revises: add_prepared_board_cache
"""
from alembic import op

revision = "add_odds_history_clv"
down_revision = "add_prepared_board_cache"
branch_labels = None
depends_on = None


def upgrade():
    from leagues.odds_history import ensure_odds_history_schema
    ensure_odds_history_schema(op.get_bind())


def downgrade():
    # Immutable price evidence must survive code rollback.
    pass
