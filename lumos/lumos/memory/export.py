"""Writing saved memories out to a file on this machine.

Kept apart from ``database.py``, which is SQLite and nothing else, and from
``cli.py``, which is presentation and nothing else. The separation is also the
privacy boundary, and the reason this module takes a database and a directory
rather than ``Settings``: there is no API key, base URL or token anywhere in its
reach, so an export cannot leak a secret it was never handed. It reads one table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lumos.memory.database import Database

EXPORT_FORMAT = "lumos.memories"
EXPORT_VERSION = 1


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Where the export went, and how much of it there was.

    ``path`` is None when there was nothing to write.
    """

    path: Path | None
    count: int


class ExportError(RuntimeError):
    """An export that refused to run rather than destroy what was already there."""


def _filename(moment: datetime) -> str:
    return f"lumos-memories-{moment.strftime('%Y%m%dT%H%M%SZ')}.json"


def _entry(row: dict[str, Any]) -> dict[str, Any]:
    """One memory, as an export describes it.

    Written out key by key rather than handed the row, so a column added to
    `memories` later cannot quietly start appearing in files people have already
    exported and shared. `memory_key` becomes `key`: the column name carries a
    prefix that only makes sense inside the table.
    """
    return {
        "id": row["id"],
        "namespace": row["namespace"],
        "key": row["memory_key"],
        "value": row["value"],
        "importance": row["importance"],
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def export_memories(database: Database, *, directory: Path) -> ExportResult:
    """Write every saved memory to a new timestamped JSON file under ``directory``.

    The filename carries the UTC second it was written, so an export never lands
    on an earlier one; if it somehow does, it refuses rather than overwrite. A
    backup that silently replaces the backup you were relying on is worse than no
    backup at all.
    """
    rows = database.list_memories(limit=None)
    if not rows:
        # Nothing to export is not a failure, but it is not a file either: an empty
        # export is only something to find in a year and misread as a loss.
        return ExportResult(path=None, count=0)

    moment = datetime.now(UTC)
    payload = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": moment.isoformat(),
        "count": len(rows),
        "memories": [_entry(row) for row in rows],
    }

    # Made only now: a folder for exports has no business existing until there is
    # something to put in it.
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _filename(moment)
    try:
        # "x" and not "w": the check and the claim are one step, so two exports in
        # the same second lose the race rather than the file.
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise ExportError(
            f"An export already exists at {path}; nothing was written. Try again in a second."
        ) from exc
    return ExportResult(path=path, count=len(rows))
