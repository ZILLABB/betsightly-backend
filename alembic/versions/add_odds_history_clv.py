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
    from leagues.odds_history import metadata
    bind = op.get_bind()
    metadata.create_all(bind, checkfirst=True)
    for table in ("odds_observations", "odds_selection_entries"):
        if bind.dialect.name == "postgresql":
            op.execute("""
                CREATE OR REPLACE FUNCTION odds_history_reject_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'odds history is append-only'; END;
                $$
            """)
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
            op.execute(f"CREATE TRIGGER trg_{table}_immutable "
                       f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
                       "EXECUTE FUNCTION odds_history_reject_mutation()")
        elif bind.dialect.name == "sqlite":
            for action in ("UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER IF NOT EXISTS trg_{table}_{action.lower()} "
                           f"BEFORE {action} ON {table} BEGIN "
                           "SELECT RAISE(ABORT, 'odds history is append-only'); END")


def downgrade():
    # Immutable price evidence must survive code rollback.
    pass
