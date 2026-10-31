"""unique recipe slug

Edit, delete and "cooked" find a recipe by its slug, and "Chili" and "Chili!"
both slugify to `chili`, so one acted on the other. Existing duplicates keep
the oldest recipe's slug; the others get -2, -3, ... (their /recipes/<slug>
links change), then the index becomes unique.

Revision ID: b3e8f1a2c4d6
Revises: 7a1c0e5d2b44
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3e8f1a2c4d6"
down_revision: Union[str, Sequence[str], None] = "7a1c0e5d2b44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("select id, slug from recipe order by id")).all()
    taken = {slug for _, slug in rows}
    seen: set[str] = set()
    for rid, slug in rows:
        if slug not in seen:
            seen.add(slug)
            continue
        n = 2
        while f"{slug}-{n}" in taken:
            n += 1
        new = f"{slug}-{n}"
        taken.add(new)
        seen.add(new)
        conn.execute(sa.text("update recipe set slug = :s where id = :i"), {"s": new, "i": rid})
    with op.batch_alter_table("recipe") as batch_op:
        batch_op.drop_index("ix_recipe_slug")
        batch_op.create_index("ix_recipe_slug", ["slug"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("recipe") as batch_op:
        batch_op.drop_index("ix_recipe_slug")
        batch_op.create_index("ix_recipe_slug", ["slug"], unique=False)
