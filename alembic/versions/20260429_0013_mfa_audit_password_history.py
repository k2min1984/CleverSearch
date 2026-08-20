"""add mfa columns + audit_logs + auth_password_history

- auth_users.mfa_secret / mfa_enabled
- auth_password_history (직전 N개 재사용 차단)
- audit_logs (로그인/권한/관리 작업 영속 기록)

Revision ID: 20260429_0013
Revises: 20260429_0012
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa


revision = "20260429_0013"
down_revision = "20260429_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1) auth_users 컬럼 추가
    if "auth_users" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("auth_users")}
        if "mfa_secret" not in cols:
            op.add_column("auth_users", sa.Column("mfa_secret", sa.String(length=64), nullable=True))
        if "mfa_enabled" not in cols:
            op.add_column("auth_users", sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        idxs = {idx["name"] for idx in inspector.get_indexes("auth_users")}
        if "ix_auth_users_mfa_enabled" not in idxs:
            op.create_index("ix_auth_users_mfa_enabled", "auth_users", ["mfa_enabled"])

    # 2) auth_password_history
    if "auth_password_history" not in existing_tables:
        op.create_table(
            "auth_password_history",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("auth_users.id"), nullable=False, index=True),
            sa.Column("password_hash", sa.String(length=400), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_auth_password_history_user_created", "auth_password_history", ["user_id", "created_at"])

    # 3) audit_logs
    if "audit_logs" not in existing_tables:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), index=True),
            sa.Column("actor", sa.String(length=120), nullable=True, index=True),
            sa.Column("actor_role", sa.String(length=40), nullable=True, index=True),
            sa.Column("action", sa.String(length=80), nullable=False, index=True),
            sa.Column("target", sa.String(length=200), nullable=True, index=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="success", index=True),
            sa.Column("ip", sa.String(length=64), nullable=True, index=True),
            sa.Column("user_agent", sa.String(length=400), nullable=True),
            sa.Column("detail", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "audit_logs" in existing:
        op.drop_table("audit_logs")
    if "auth_password_history" in existing:
        op.drop_table("auth_password_history")
    if "auth_users" in existing:
        cols = {c["name"] for c in inspector.get_columns("auth_users")}
        idxs = {idx["name"] for idx in inspector.get_indexes("auth_users")}
        if "ix_auth_users_mfa_enabled" in idxs:
            op.drop_index("ix_auth_users_mfa_enabled", table_name="auth_users")
        if "mfa_enabled" in cols:
            op.drop_column("auth_users", "mfa_enabled")
        if "mfa_secret" in cols:
            op.drop_column("auth_users", "mfa_secret")
