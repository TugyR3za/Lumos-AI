from __future__ import annotations

import uvicorn

from lumos.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "lumos.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "development",
    )


if __name__ == "__main__":
    main()
