"""Lumos launcher.

    python run.py            # terminal chat (default)
    python run.py cli        # terminal chat
    python run.py web        # web UI at http://127.0.0.1:8000
    python run.py reindex    # (re)index notes and exit
"""

from __future__ import annotations

import sys


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "cli"

    if mode == "cli":
        from lumos.ui.cli import run
        run()
    elif mode == "web":
        from lumos.ui.web import run
        run()
    elif mode == "reindex":
        from lumos.app import build_app
        force = "force" in sys.argv
        print(build_app().reindex(force=force))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
