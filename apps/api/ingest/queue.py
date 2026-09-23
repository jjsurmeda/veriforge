"""Procrastinate app (TRD §9.1 worker; ADR-001: Postgres is the queue).

The `queue` schema (migration 0003, TRD §13) is selected via search_path.
The API process opens this app in the lifespan to defer jobs; workers run
it via `procrastinate --app=ingest.worker.app worker <queue>`.
"""

import procrastinate

from config import get_settings

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(
        conninfo=get_settings().procrastinate_conninfo,
        kwargs={"options": "-c search_path=queue"},
    ),
)
