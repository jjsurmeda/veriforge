"""Per-run sequence counters, so `run_events.seq` is allocated by the
database instead of raced for (KI-68).

`PostgresRunBus.publish` used to pick a number with
`SELECT COALESCE(MAX(seq),0)+1` and insert in a second statement. That is a
read-then-write with nothing serialising it, so two publishers on one run
could pick the same number, and the loser spent one of `SEQ_RACE_RETRIES`
attempts on the `run_events` primary key. Lane B item 2 made the per-variant
searches concurrent — and gave each one its own `step.started`/`step.completed`
pair — so contention on one run's counter stopped being incidental. Three
attempts were then three chances to lose, and one run in forty died with
`duplicate key value violates unique constraint "run_events_pkey"` before
the generator, which is the worst shape a failure takes: no text, no decline.

This table is the fix's whole mechanism. One row per run, incremented by

    INSERT … ON CONFLICT (run_id) DO UPDATE SET last_seq = last_seq + 1
    RETURNING last_seq

which takes a row lock Postgres holds to COMMIT, so publishers on one run
are serialised by the database rather than by our retry budget. Three
properties come from putting the increment in the *same transaction* as the
insert, which is why the counter is a column rather than a sequence:

- **Gapless.** A publish that rolls back after taking its number gives it
  back, because the increment rolls back with it. A gap in a run's sequence
  is not cosmetic — `subscribe(after_seq=…)` walks it.
- **Ordered.** Allocation order is commit order, because a publisher cannot
  take a number until the previous holder has committed. A subscriber
  therefore replays events in the order the database granted them.

`ON DELETE CASCADE` is what keeps this table honest: the counter's life is
exactly the run's life, so deleting a run cannot leave an orphan pointing
at a run that no longer exists.

ADR-001 is unaffected — this is a Postgres table behind the RunBus, not a
Redis counter, and no other store was introduced.

Downgrade drops the table. Nothing outside `runbus/postgres.py` reads it,
so a downgrade costs the sequence numbering and nothing else; the old
`MAX(seq)+1` read is still exactly what the column is initialised from.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_seq_counters",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "last_seq",
            sa.Integer(),
            nullable=False,
            comment="the highest seq this run has committed; next is +1",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
    )
    # Runs that already have events start from their real maximum, so a
    # deployment mid-run does not re-issue a number that is already stored.
    # Runs with no events get no row: the upsert inserts one at 1.
    op.execute(
        "INSERT INTO run_seq_counters (run_id, last_seq) "
        "SELECT run_id, MAX(seq) FROM run_events GROUP BY run_id"
    )


def downgrade() -> None:
    op.drop_table("run_seq_counters")
