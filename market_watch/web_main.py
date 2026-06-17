"""Run the Market Watch web server."""
import uvicorn

from market_watch.config import ROOT_DIR


def main() -> None:
    uvicorn.run(
        "market_watch.api.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
