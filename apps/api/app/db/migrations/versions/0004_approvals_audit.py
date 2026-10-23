"""approvals, tool executions, clause flags and the append-only audit log

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _created_at() -> "sa.Column[datetime]":
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    app_role = context.config.attributes["app_db_user"]

    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_id", sa.Uuid(), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("call_id", sa.String(100), nullable=False),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=False),
        sa.Column("edited_args", postgresql.JSONB()),
        sa.Column("json_schema", postgresql.JSONB(), nullable=False),
        sa.Column("risk", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')", name="ck_approvals_status"
        ),
        sa.CheckConstraint("risk IN ('low', 'medium', 'high')", name="ck_approvals_risk"),
    )
    op.create_index("ix_approvals_pending", "approvals", ["tenant_id", "status", "created_at"])
    op.create_index("ix_approvals_run", "approvals", ["run_id"])

    op.create_table(
        "tool_executions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        # One execution per approval: retries and double clicks can't send an email twice.
        sa.Column(
            "approval_id",
            sa.Uuid(),
            sa.ForeignKey("approvals.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", postgresql.JSONB()),
        _created_at(),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name="ck_tool_executions_status"
        ),
    )

    op.create_table(
        "clause_flags",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("chunk_id", sa.Uuid(), sa.ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("flagged_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        _created_at(),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        # No foreign keys to users: ON DELETE SET NULL would be an UPDATE, which this table refuses.
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("details", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        _created_at(),
    )
    op.create_index("ix_audit_log_tenant_recent", "audit_log", ["tenant_id", sa.text("id DESC")])

    for table in ("approvals", "tool_executions", "clause_flags", "audit_log"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = {CURRENT_TENANT}) WITH CHECK (tenant_id = {CURRENT_TENANT})"
        )

    # Append-only: the app may add and read audit entries, never change or remove them. The
    # trigger also stops the owner role; only dropping the trigger (a migration) could.
    op.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM "{app_role}"')
    op.execute(
        """
        CREATE FUNCTION audit_log_is_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_is_append_only()"
    )
    _expiry_function(app_role)


def _expiry_function(app_role: str) -> None:
    # Runs for every tenant at once (a worker cron), so it can't use the per-tenant RLS setting:
    # SECURITY DEFINER runs it as the owner. It only ever expires overdue pending approvals,
    # closes runs left with nothing to wait for, and records both in the audit log.
    op.execute(
        """
        CREATE FUNCTION expire_stale_approvals()
        RETURNS TABLE (tenant_id uuid, approval_id uuid, run_id uuid, chat_id uuid,
                       tool text, requested_by uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
            WITH expired AS (
                UPDATE approvals
                SET status = 'expired', decided_at = now(), reason = 'Expired before a decision.'
                WHERE status = 'pending' AND expires_at < now()
                RETURNING approvals.tenant_id, approvals.id, approvals.run_id,
                          approvals.chat_id, approvals.tool, approvals.requested_by
            ), closed AS (
                UPDATE runs SET status = 'cancelled', finished_at = now(),
                                error = '{"code": "approval_expired"}'::jsonb
                WHERE runs.status = 'awaiting_approval'
                  AND runs.id IN (SELECT expired.run_id FROM expired)
                  AND NOT EXISTS (
                      SELECT 1 FROM approvals a
                      WHERE a.run_id = runs.id AND a.status = 'pending'
                        AND a.id NOT IN (SELECT expired.id FROM expired))
                RETURNING runs.id
            ), logged AS (
                INSERT INTO audit_log (tenant_id, actor, action, target_type, target_id, details)
                SELECT expired.tenant_id, 'system', 'approval.expired', 'approval',
                       expired.id::text, jsonb_build_object('tool', expired.tool)
                FROM expired
                RETURNING 1
            )
            SELECT expired.tenant_id, expired.id, expired.run_id, expired.chat_id,
                   expired.tool, expired.requested_by
            FROM expired;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION expire_stale_approvals() FROM PUBLIC")
    op.execute(f'GRANT EXECUTE ON FUNCTION expire_stale_approvals() TO "{app_role}"')


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS expire_stale_approvals()")
    op.execute("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_is_append_only()")
    op.drop_table("audit_log")
    op.drop_table("clause_flags")
    op.drop_table("tool_executions")
    op.drop_table("approvals")
