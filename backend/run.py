"""Start the API using the host/port from backend/.env.

The uvicorn CLI can't read .env, so this wrapper loads it first and then hands
the values to uvicorn — meaning `python backend/run.py` needs no flags.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")

# So `app.main` resolves no matter which directory you launch from.
sys.path.insert(0, str(BACKEND_DIR))


def main() -> None:
    import uvicorn

    host = os.getenv("LC_HOST", "127.0.0.1")
    # Hosts like Render/Railway inject PORT; honour it so the same entry point
    # works locally and deployed.
    port = int(os.getenv("PORT") or os.getenv("LC_PORT") or 8101)

    # ASCII only — the Windows console defaults to cp1252 and dies on box/arrow glyphs.
    print(f"LC DealMate API on http://{host}:{port}")
    uvicorn.run("app.main:app", host=host, port=port)


if __name__ == "__main__":
    main()
