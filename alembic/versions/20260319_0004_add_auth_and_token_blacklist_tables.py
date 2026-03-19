"""add auth and token blacklist tables

Revision ID: 20260319_0004
Revises: 20260319_0003
Create Date: 2026-03-19
"""

from alembic import op
import sqlalchemy as sa


revision = "20260319_0004"
down_revision = "20260319_0003"
branch_labels = None
depends_on = None


def _is_postgresql() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "auth_roles" not in existing_tables:
        op.create_table(
            "auth_roles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=50), nullable=False),
            sa.Column("description", sa.String(length=200), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_auth_roles_name", "auth_roles", ["name"], unique=True)
        op.create_index("ix_auth_roles_is_active", "auth_roles", ["is_active"])
        op.create_index("ix_auth_roles_created_at", "auth_roles", ["created_at"])

    if "auth_users" not in existing_tables:
        op.create_table(
            "auth_users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("username", sa.String(length=120), nullable=False),
            sa.Column("password_hash", sa.String(length=400), nullable=False),
            sa.Column("role_id", sa.Integer(), sa.ForeignKey("auth_roles.id"), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_auth_users_username", "auth_users", ["username"], unique=True)
        op.create_index("ix_auth_users_role_id", "auth_users", ["role_id"])
        op.create_index("ix_auth_users_is_active", "auth_users", ["is_active"])
        op.create_index("ix_auth_users_created_at", "auth_users", ["created_at"])
        op.create_index("ix_auth_users_updated_at", "auth_users", ["updated_at"])

    if "revoked_access_tokens" not in existing_tables:
        op.create_table(
            "revoked_access_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("jti", sa.String(length=120), nullable=False),
            sa.Column("subject", sa.String(length=120), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_revoked_access_tokens_jti", "revoked_access_tokens", ["jti"], unique=True)
        op.create_index("ix_revoked_access_tokens_subject", "revoked_access_tokens", ["subject"])
        op.create_index("ix_revoked_access_tokens_expires_at", "revoked_access_tokens", ["expires_at"])
        op.create_index("ix_revoked_access_tokens_revoked_at", "revoked_access_tokens", ["revoked_at"])

    if "revoked_refresh_tokens" not in existing_tables:
        op.create_table(
            "revoked_refresh_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("jti", sa.String(length=120), nullable=False),
            sa.Column("subject", sa.String(length=120), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_revoked_refresh_tokens_jti", "revoked_refresh_tokens", ["jti"], unique=True)
        op.create_index("ix_revoked_refresh_tokens_subject", "revoked_refresh_tokens", ["subject"])
        op.create_index("ix_revoked_refresh_tokens_expires_at", "revoked_refresh_tokens", ["expires_at"])
        op.create_index("ix_revoked_refresh_tokens_revoked_at", "revoked_refresh_tokens", ["revoked_at"])

    if _is_postgresql():
        op.execute("COMMENT ON TABLE auth_roles IS '시스템 권한 역할 테이블'")
        op.execute("COMMENT ON TABLE auth_users IS '인증 사용자 계정 테이블'")
        op.execute("COMMENT ON TABLE revoked_access_tokens IS 'Access token 블랙리스트 테이블'")
        op.execute("COMMENT ON TABLE revoked_refresh_tokens IS 'Refresh token 블랙리스트 테이블'")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "revoked_refresh_tokens" in existing_tables:
        op.drop_index("ix_revoked_refresh_tokens_revoked_at", table_name="revoked_refresh_tokens")
        op.drop_index("ix_revoked_refresh_tokens_expires_at", table_name="revoked_refresh_tokens")
        op.drop_index("ix_revoked_refresh_tokens_subject", table_name="revoked_refresh_tokens")
        op.drop_index("ix_revoked_refresh_tokens_jti", table_name="revoked_refresh_tokens")
        op.drop_table("revoked_refresh_tokens")

    if "revoked_access_tokens" in existing_tables:
        op.drop_index("ix_revoked_access_tokens_revoked_at", table_name="revoked_access_tokens")
        op.drop_index("ix_revoked_access_tokens_expires_at", table_name="revoked_access_tokens")
        op.drop_index("ix_revoked_access_tokens_subject", table_name="revoked_access_tokens")
        op.drop_index("ix_revoked_access_tokens_jti", table_name="revoked_access_tokens")
        op.drop_table("revoked_access_tokens")

    if "auth_users" in existing_tables:
        op.drop_index("ix_auth_users_updated_at", table_name="auth_users")
        op.drop_index("ix_auth_users_created_at", table_name="auth_users")
        op.drop_index("ix_auth_users_is_active", table_name="auth_users")
        op.drop_index("ix_auth_users_role_id", table_name="auth_users")
        op.drop_index("ix_auth_users_username", table_name="auth_users")
        op.drop_table("auth_users")

    if "auth_roles" in existing_tables:
        op.drop_index("ix_auth_roles_created_at", table_name="auth_roles")
        op.drop_index("ix_auth_roles_is_active", table_name="auth_roles")
        op.drop_index("ix_auth_roles_name", table_name="auth_roles")
        op.drop_table("auth_roles")
