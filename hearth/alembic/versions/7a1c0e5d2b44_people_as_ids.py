"""people as ids, household

Votes and garment owners referenced a person by lowercased name, so renaming
someone orphaned everything they had voted on. They now reference user ids 1
and 2 — the app's two fixed slots — and the names live in `user`, editable
from Settings. `household` holds the home location, the setup flag and the
last backup's outcome.

Revision ID: 7a1c0e5d2b44
Revises: c9d77a53878c
"""
import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7a1c0e5d2b44"
down_revision: Union[str, Sequence[str], None] = "c9d77a53878c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _names(conn) -> list[str]:
    """The two people, slot order. HEARTH_PEOPLE wins; otherwise whoever has
    voted or owns a garment. Raises before anything has changed."""
    env = [p.strip().lower() for p in os.environ.get("HEARTH_PEOPLE", "").split(",")
           if p.strip()]
    seen = sorted({r[0] for r in conn.execute(sa.text(
        "select person from verdict union select owner from garment where owner != ''"))})
    names = env or seen
    unknown = [n for n in seen if n not in names]
    if unknown or len(names) > 2:
        raise RuntimeError(
            f"people-as-ids: cannot map {unknown or names} onto two people. "
            "Set HEARTH_PEOPLE to the two names your votes use and run it again. "
            "Nothing was changed.")
    return names


def _home() -> tuple[float | None, float | None]:
    raw = os.environ.get("HEARTH_HOME_LATLON", "")
    try:
        lat, lon = (float(x) for x in raw.split(","))
    except ValueError:
        return None, None
    return (None, None) if (lat, lon) == (0.0, 0.0) else (lat, lon)


def upgrade() -> None:
    conn = op.get_bind()
    names = _names(conn)

    op.create_table(
        "household",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("home_lat", sa.Float(), nullable=True),
        sa.Column("home_lon", sa.Float(), nullable=True),
        sa.Column("setup_done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_backup_at", sa.DateTime(), nullable=True),
        sa.Column("last_backup_ok", sa.Boolean(), nullable=True),
        sa.Column("last_backup_error", sa.String(), nullable=False, server_default=""),
    )
    lat, lon = _home()
    conn.execute(sa.text(
        "insert into household (id, home_lat, home_lon, setup_done, last_backup_error) "
        "values (1, :lat, :lon, :done, '')"),
        {"lat": lat, "lon": lon, "done": len(names) == 2})

    conn.execute(sa.text('delete from "user"'))
    for slot in (1, 2):
        name = names[slot - 1].capitalize() if len(names) >= slot else ""
        conn.execute(sa.text(
            'insert into "user" (id, display_name, email, is_admin) values (:id, :n, \'\', 0)'),
            {"id": slot, "n": name})
    with op.batch_alter_table("user") as b:
        b.drop_column("email")

    with op.batch_alter_table("verdict") as b:
        b.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
    for slot, name in enumerate(names, 1):
        conn.execute(sa.text("update verdict set user_id = :s where person = :n"),
                     {"s": slot, "n": name})
    with op.batch_alter_table("verdict") as b:
        b.drop_index("ix_verdict_unique")
        b.drop_index("ix_verdict_person")
        b.drop_column("person")
        b.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
        b.create_index("ix_verdict_user_id", ["user_id"])
        b.create_index("ix_verdict_unique", ["user_id", "kind", "row_id"], unique=True)

    with op.batch_alter_table("garment") as b:
        b.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
    for slot, name in enumerate(names, 1):
        conn.execute(sa.text("update garment set owner_id = :s where owner = :n"),
                     {"s": slot, "n": name})
    with op.batch_alter_table("garment") as b:
        b.drop_index("ix_garment_owner")
        b.drop_column("owner")


def downgrade() -> None:
    raise NotImplementedError(
        "No automatic downgrade: restore the hearth-prestart-*.db.gz backup taken before "
        "this migration ran (README, 'Rolling back').")
