"""replace email with mobile_phone and add profile_image

Revision ID: df8528d4e8cc
Revises:
Create Date: 2026-02-03 12:23:16.304441
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "df8528d4e8cc"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Users table with mobile_phone and profile_image
    op.create_table(
        "users",
        sa.Column("id", mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("student_id_no", mysql.VARCHAR(length=20), nullable=True),
        sa.Column("first_name", mysql.VARCHAR(length=100), nullable=False),
        sa.Column("last_name", mysql.VARCHAR(length=100), nullable=False),
        sa.Column("middle_initial", mysql.VARCHAR(length=5), nullable=True),
        sa.Column("program", mysql.VARCHAR(length=100), nullable=True),
        sa.Column("role", mysql.ENUM("STUDENT", "ADMIN"), nullable=False),
        sa.Column("mobile_phone", mysql.VARCHAR(length=20), nullable=True),
        sa.Column("profile_image", mysql.VARCHAR(length=255), nullable=True),
        sa.Column("password", mysql.VARCHAR(length=255), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(),
            server_default=sa.text("(now())"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(),
            server_default=sa.text("(now())"),
            nullable=True,
        ),
        sa.Column(
            "fingerprint_status",
            mysql.ENUM("not_enrolled", "pending", "enrolled", "failed"),
            server_default=sa.text("'not_enrolled'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            mysql.VARCHAR(length=20),
            server_default=sa.text("'not_enrolled'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_default_charset="utf8mb4",
        mysql_engine="InnoDB",
    )

    # Indexes for users table
    op.create_index(
        op.f("ix_users_student_id_no"), "users", ["student_id_no"], unique=True
    )
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(
        op.f("ix_users_mobile_phone"), "users", ["mobile_phone"], unique=True
    )

    # Other tables can follow...
    # notifications, events, fingerprints, push_subscriptions, password_resets
    # can be added here as needed.


def downgrade() -> None:
    """Downgrade schema."""
    # Restore users table to previous state with email
    op.create_table(
        "users",
        sa.Column("id", mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("student_id_no", mysql.VARCHAR(length=20), nullable=True),
        sa.Column("first_name", mysql.VARCHAR(length=100), nullable=False),
        sa.Column("last_name", mysql.VARCHAR(length=100), nullable=False),
        sa.Column("middle_initial", mysql.VARCHAR(length=5), nullable=True),
        sa.Column("program", mysql.VARCHAR(length=100), nullable=True),
        sa.Column("role", mysql.ENUM("STUDENT", "ADMIN"), nullable=False),
        sa.Column("email", mysql.VARCHAR(length=255), nullable=False),
        sa.Column("password", mysql.VARCHAR(length=255), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(),
            server_default=sa.text("(now())"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(),
            server_default=sa.text("(now())"),
            nullable=True,
        ),
        sa.Column(
            "fingerprint_status",
            mysql.ENUM("not_enrolled", "pending", "enrolled", "failed"),
            server_default=sa.text("'not_enrolled'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            mysql.VARCHAR(length=20),
            server_default=sa.text("'not_enrolled'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_default_charset="utf8mb4",
        mysql_engine="InnoDB",
    )

    # Indexes for old users table
    op.create_index(
        op.f("ix_users_student_id_no"), "users", ["student_id_no"], unique=True
    )
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    # Other tables can follow downgrade logic as before...
    # notifications
    op.create_table(
        "notifications",
        sa.Column("id", mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("event_id", mysql.INTEGER(), autoincrement=False, nullable=True),
        sa.Column("title", mysql.VARCHAR(length=255), nullable=False),
        sa.Column("message", mysql.TEXT(), nullable=False),
        sa.Column("type", mysql.VARCHAR(length=50), nullable=False),
        sa.Column(
            "is_read",
            mysql.TINYINT(display_width=1),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "timestamp",
            mysql.DATETIME(),
            server_default=sa.text("(now())"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("notifications_ibfk_2"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("notifications_ibfk_1"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_default_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(op.f("ix_notifications_id"), "notifications", ["id"], unique=False)

    # events table
    op.create_table(
        "events",
        sa.Column("id", mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("title", mysql.VARCHAR(length=255), nullable=False),
        sa.Column("description", mysql.TEXT(), nullable=True),
        sa.Column("event_date", sa.DATE(), nullable=False),
        sa.Column("start_time", mysql.TIME(), nullable=False),
        sa.Column("end_time", mysql.TIME(), nullable=False),
        sa.Column("location", mysql.VARCHAR(length=255), nullable=False),
        sa.Column("created_by", mysql.INTEGER(), autoincrement=False, nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(),
            server_default=sa.text("(now())"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("events_ibfk_1")
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_default_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(op.f("ix_events_id"), "events", ["id"], unique=False)

    # fingerprints table
    op.create_table(
        "fingerprints",
        sa.Column("id", mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("fingerprint_template", sa.BLOB(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(),
            server_default=sa.text("(now())"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fingerprints_ibfk_1"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_default_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_fingerprints_user_id"), "fingerprints", ["user_id"], unique=False
    )
    op.create_index(op.f("ix_fingerprints_id"), "fingerprints", ["id"], unique=False)

    # push_subscriptions table
    op.create_table(
        "push_subscriptions",
        sa.Column("id", mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.INTEGER(), autoincrement=False, nullable=True),
        sa.Column("subscription", mysql.JSON(), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(),
            server_default=sa.text("(now())"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("push_subscriptions_ibfk_1"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_default_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(op.f("user_id"), "push_subscriptions", ["user_id"], unique=True)

    # password_resets table
    op.create_table(
        "password_resets",
        sa.Column("id", mysql.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("user_id", mysql.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("token", mysql.VARCHAR(length=255), nullable=False),
        sa.Column("created_at", mysql.DATETIME(), nullable=True),
        sa.Column("expires_at", mysql.DATETIME(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("password_resets_ibfk_1")
        ),
        sa.PrimaryKeyConstraint("id"),
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_default_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_password_resets_token"), "password_resets", ["token"], unique=True
    )
    op.create_index(
        op.f("ix_password_resets_id"), "password_resets", ["id"], unique=False
    )
