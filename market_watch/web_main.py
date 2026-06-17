"""Run the Market Watch web server."""
import os

import uvicorn

from market_watch.config import ROOT_DIR


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "market_watch.api.app:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
