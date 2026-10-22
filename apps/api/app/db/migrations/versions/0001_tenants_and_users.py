"""tenants and users with row-level security

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# NULLIF: once set in a session, an unset transaction-local GUC reads back as '' not NULL.
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    app_role = context.config.attributes["app_db_user"]

    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{app_role}') THEN
                CREATE ROLE "{app_role}" NOLOGIN NOSUPERUSER NOBYPASSRLS;
            END IF;
        END $$
        """
    )

    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("oidc_sub", sa.String(255), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320)),
        sa.Column("display_name", sa.String(255)),
        sa.Column("locale", sa.String(8), server_default="en", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "oidc_sub"),
    )

    for table, column in (("tenants", "id"), ("users", "tenant_id")):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({column} = {CURRENT_TENANT}) WITH CHECK ({column} = {CURRENT_TENANT})"
        )

    op.execute(f'GRANT USAGE ON SCHEMA public TO "{app_role}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON tenants, users TO "{app_role}"')
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
    )


def downgrade() -> None:
    op.drop_table("users")
    op.drop_table("tenants")
