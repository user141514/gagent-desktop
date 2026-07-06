from __future__ import annotations

import argparse
import os

import uvicorn

from .app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GenericAgent React API server.")
    parser.add_argument("--host", default=os.getenv("GA_REACT_API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("GA_REACT_API_PORT", "8765")))
    parser.add_argument("--backend", default=os.getenv("GA_REACT_BACKEND", "classic"))
    args = parser.parse_args()

    app = create_app(backend=args.backend, project_root=os.getcwd())
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
