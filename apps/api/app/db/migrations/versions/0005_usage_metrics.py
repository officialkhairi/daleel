"""run metrics, users' last-seen roles, and the usage_daily view

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("ttft_ms", sa.Integer()))
    op.add_column("runs", sa.Column("latency_ms", sa.Integer()))
    op.add_column("runs", sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False))
    op.add_column("runs", sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False))
    op.add_column(
        "runs", sa.Column("cost_usd", sa.Numeric(12, 6), server_default="0", nullable=False)
    )
    op.add_column(
        "users",
        sa.Column(
            "roles",
            postgresql.ARRAY(sa.String(32)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )

    # A plain view with security_invoker, not a materialized view: Postgres can't apply row-level
    # security to materialized views, and this must only ever show the caller's tenant. The data
    # is small (one row per run), so computing it on read is cheap.
    op.execute(
        """
        CREATE VIEW usage_daily WITH (security_invoker = true) AS
        SELECT
            tenant_id,
            (created_at AT TIME ZONE 'UTC')::date AS day,
            model,
            count(*) AS runs,
            count(*) FILTER (WHERE status = 'failed') AS failed,
            count(*) FILTER (WHERE status = 'awaiting_approval'
                             OR state ? 'pending') AS paused_for_approval,
            sum(tokens_in) AS tokens_in,
            sum(tokens_out) AS tokens_out,
            sum(cost_usd) AS cost_usd,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY ttft_ms) AS ttft_p50_ms,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY ttft_ms) AS ttft_p95_ms,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS latency_p50_ms
        FROM runs
        GROUP BY tenant_id, (created_at AT TIME ZONE 'UTC')::date, model
        """
    )
    # Read access comes from 0001's default privileges; aggregates make the view read-only.


def downgrade() -> None:
    op.execute("DROP VIEW usage_daily")
    op.drop_column("users", "roles")
    for column in ("cost_usd", "tokens_out", "tokens_in", "latency_ms", "ttft_ms"):
        op.drop_column("runs", column)
