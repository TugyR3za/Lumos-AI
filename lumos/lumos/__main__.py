"""Lumos launcher.

Usage:
    python -m lumos            web UI at http://127.0.0.1:8000 (default)
    python -m lumos web        web UI
    python -m lumos cli        terminal chat, the lightest option
    python -m lumos reindex    index the notes folder and exit
"""

from __future__ import annotations

import sys


def _run_web() -> None:
    import uvicorn

    from lumos.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "lumos.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "development",
    )


def _run_reindex() -> None:
    from lumos.config import get_settings
    from lumos.core.container import build_container

    container = build_container(get_settings())
    stats = container.ingestor.ingest_all()
    print(
        f"Scanned {stats.scanned} files: {stats.indexed} indexed, "
        f"{stats.skipped} unchanged, {stats.removed} removed, {stats.chunks} chunks."
    )


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "web"
    if mode == "web":
        _run_web()
    elif mode == "cli":
        from lumos.cli import run

        run()
    elif mode == "reindex":
        _run_reindex()
    elif mode in ("help", "-h", "--help"):
        print(__doc__)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
