"""Which commit this process is serving, read from git at boot.

A quality run has to prove it measured the branch under test. `make acceptance`
talks to a *running* api, and the dev api is a hot-reloading process off
whatever checkout started it — so a run on a worktree can be scored against
code from the main checkout without anything looking wrong. The served commit
is what makes that visible: the api reports the commit its own code came from,
and the caller compares it with the commit it meant to test.

Read once, from `git rev-parse HEAD` in the repository root, and cached: this
runs on every `/healthz` and the answer cannot change while the process is up.
A checkout with no git (a container image built from an exported tree) reports
`unknown`, which is deliberately not a silent pass — a run that cannot name its
commit has not proved what it measured.

Two deliberate choices:

- **The full sha, not the short one.** `make check-work` compares it against
  `git rev-parse HEAD`, and a 7-character prefix is a weaker identity than the
  comparison needs.
- **No `VERIFORGE_COMMIT` override.** An env var would let the operator assert
  the commit rather than report it, which is exactly the mistake this exists to
  catch: the value has to come from the checkout the code was loaded from.
"""

import subprocess
from functools import cache
from pathlib import Path

# apps/api/build_info.py -> the repository root.
REPO_ROOT = Path(__file__).resolve().parents[2]

UNKNOWN = "unknown"


@cache
def served_commit() -> str:
    """The commit this process's code came from, or `unknown`.

    Cached for the life of the process: the working tree can move under a
    running server (that is what the hot-reloading dev api is for), so
    re-reading git per request would report the checkout's *current* HEAD
    rather than the commit the code was loaded from — which is the value that
    has to be checked.
    """
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
            cwd=REPO_ROOT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN
    sha = completed.stdout.strip()
    if completed.returncode != 0 or not sha:
        return UNKNOWN
    return sha