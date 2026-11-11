"""add punch cards: the punch_cards table, check-ins charged to a card, and
a price for the card (decision 0042).

Revision ID: 8e3f21ab05b0
Revises: b0ca1ec058f5
Create Date: 2026-11-11 10:43:47.205823+00:00

- ``punch_cards``: a new, empty table. Two triggers make it append-only.
- ``checkins``: a nullable ``punch_card_id`` (FK, indexed); every existing
  row gets NULL. Adding a foreign key rebuilds the table (batch mode), and
  SQLite drops a table's triggers with it, so its three triggers are
  dropped first and created again unchanged, plus two new ones: the card
  is the same customer's, and a card has at most 20 check-ins (``CARD_
  ENTRIES`` in ``app.core.models.punch_cards``).
- ``prices``: the plan CHECK also allows ``punch_card``. The table is
  rebuilt; it has no triggers. ``plan_choices`` keeps its three plans.

No existing row changes. ``downgrade()`` is a full undo while no punch
card and no punch-card price exist. Once one does, it refuses: undoing
would throw away what customers paid for.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "8e3f21ab05b0"
down_revision: str | Sequence[str] | None = "b0ca1ec058f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Reflect only the rebuilt table, not the tables its foreign keys name:
# SQLite can't reflect staff_users' expression index and warns on every run.
REFLECT = {"resolve_fks": False}

# checkins' triggers as they stand at 57989f782d93, unchanged.
CHECKINS_TRIGGERS = {
    "checkins_no_update": (
        "CREATE TRIGGER checkins_no_update BEFORE UPDATE ON checkins"
        " BEGIN SELECT RAISE(ABORT, 'checkins is append-only'); END"
    ),
    "checkins_no_delete": (
        "CREATE TRIGGER checkins_no_delete BEFORE DELETE ON checkins"
        " BEGIN SELECT RAISE(ABORT, 'checkins is append-only'); END"
    ),
    "checkins_same_customer_device": (
        "CREATE TRIGGER checkins_same_customer_device BEFORE INSERT ON checkins"
        " WHEN NEW.device_session_id IS NOT NULL"
        " AND (SELECT customer_id FROM device_sessions"
        " WHERE id = NEW.device_session_id) IS NOT NEW.customer_id"
        " BEGIN SELECT RAISE(ABORT,"
        " 'checkins: a phone check-in uses the same customer''s phone'); END"
    ),
}

NEW_CHECKINS_TRIGGERS = {
    "checkins_same_customer_card": (
        "CREATE TRIGGER checkins_same_customer_card BEFORE INSERT ON checkins"
        " WHEN NEW.punch_card_id IS NOT NULL"
        " AND (SELECT customer_id FROM punch_cards"
        " WHERE id = NEW.punch_card_id) IS NOT NEW.customer_id"
        " BEGIN SELECT RAISE(ABORT,"
        " 'checkins: a check-in uses the same customer''s punch card'); END"
    ),
    "checkins_card_entries": (
        "CREATE TRIGGER checkins_card_entries BEFORE INSERT ON checkins"
        " WHEN NEW.punch_card_id IS NOT NULL"
        " AND (SELECT count(*) FROM checkins"
        " WHERE punch_card_id = NEW.punch_card_id) >= 20"
        " BEGIN SELECT RAISE(ABORT,"
        " 'checkins: a punch card has 20 entries'); END"
    ),
}

PUNCH_CARDS_TRIGGERS = {
    "punch_cards_no_update": (
        "CREATE TRIGGER punch_cards_no_update BEFORE UPDATE ON punch_cards"
        " BEGIN SELECT RAISE(ABORT, 'punch_cards is append-only'); END"
    ),
    "punch_cards_no_delete": (
        "CREATE TRIGGER punch_cards_no_delete BEFORE DELETE ON punch_cards"
        " BEGIN SELECT RAISE(ABORT, 'punch_cards is append-only'); END"
    ),
}

THREE_PLANS = "\"plan\" IN ('monthly', 'tri_monthly', 'single_entry')"
FOUR_PLANS = "\"plan\" IN ('monthly', 'tri_monthly', 'single_entry', 'punch_card')"


def _set_price_plans(check: str) -> None:
    with op.batch_alter_table(
        "prices", schema=None, reflect_kwargs=REFLECT
    ) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_prices_plan"), type_="check")
        batch_op.create_check_constraint(batch_op.f("ck_prices_plan"), check)


def upgrade() -> None:
    op.create_table(
        "punch_cards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("price_agorot", sa.Integer(), nullable=False),
        sa.Column("bought_month", sa.Text(), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column("bought_at", sa.DateTime(), nullable=False),
        sa.Column(
            "bought_by",
            sa.Enum(
                "customer",
                "staff",
                name="bought_by",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("staff_user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(bought_by = 'staff') = (staff_user_id IS NOT NULL)",
            name=op.f("ck_punch_cards_staff_purchase_names_staff"),
        ),
        sa.CheckConstraint(
            "expires_on IS date(bought_month || '-01', '+2 months')",
            name=op.f("ck_punch_cards_expires_after_next_month"),
        ),
        sa.CheckConstraint(
            "length(bought_month) = 7"
            " AND bought_month >= '1000-01'"
            " AND date(bought_month || '-01') IS bought_month || '-01'",
            name=op.f("ck_punch_cards_bought_month_is_a_month"),
        ),
        sa.CheckConstraint(
            "typeof(price_agorot) = 'integer' AND price_agorot >= 0",
            name=op.f("ck_punch_cards_price_is_whole_agorot"),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_punch_cards_customer_id_customers"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            name=op.f("fk_punch_cards_staff_user_id_staff_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_punch_cards")),
    )
    op.create_index(
        op.f("ix_punch_cards_customer_id"),
        "punch_cards",
        ["customer_id", "bought_at"],
        unique=False,
    )
    for statement in PUNCH_CARDS_TRIGGERS.values():
        op.execute(statement)

    for name in CHECKINS_TRIGGERS:
        op.execute(f"DROP TRIGGER {name}")
    with op.batch_alter_table(
        "checkins", schema=None, reflect_kwargs=REFLECT
    ) as batch_op:
        batch_op.add_column(sa.Column("punch_card_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_checkins_punch_card_id"), ["punch_card_id"], unique=False
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_checkins_punch_card_id_punch_cards"),
            "punch_cards",
            ["punch_card_id"],
            ["id"],
        )
    for statement in (*CHECKINS_TRIGGERS.values(), *NEW_CHECKINS_TRIGGERS.values()):
        op.execute(statement)

    _set_price_plans(FOUR_PLANS)


def downgrade() -> None:
    connection = op.get_bind()
    cards = connection.exec_driver_sql("SELECT count(*) FROM punch_cards").scalar()
    prices = connection.exec_driver_sql(
        "SELECT count(*) FROM prices WHERE plan = 'punch_card'"
    ).scalar()
    if cards or prices:
        raise RuntimeError(
            f"can't undo punch cards: {cards} card(s) and {prices} punch-card"
            " price(s) exist, and undoing would delete them"
        )

    _set_price_plans(THREE_PLANS)

    for name in (*NEW_CHECKINS_TRIGGERS, *CHECKINS_TRIGGERS):
        op.execute(f"DROP TRIGGER {name}")
    with op.batch_alter_table(
        "checkins", schema=None, reflect_kwargs=REFLECT
    ) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_checkins_punch_card_id_punch_cards"), type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_checkins_punch_card_id"))
        batch_op.drop_column("punch_card_id")
    for statement in CHECKINS_TRIGGERS.values():
        op.execute(statement)

    for name in PUNCH_CARDS_TRIGGERS:
        op.execute(f"DROP TRIGGER {name}")
    op.drop_index(op.f("ix_punch_cards_customer_id"), table_name="punch_cards")
    op.drop_table("punch_cards")
