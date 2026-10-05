"""Bootstrap the small Render demo, then replace this process with Gunicorn.

Free Render web services do not support a separate pre-deploy command. Startup
therefore applies migrations and idempotently verifies the shipped fixtures.
All durable results live in PostgreSQL, not the ephemeral instance filesystem.
"""

import os
import subprocess
import sys
from pathlib import Path


if __name__ == "__main__":
    backend = Path(__file__).resolve().parent
    if os.getenv("LEDGERSYNC_PUBLIC_DEMO") != "1":
        raise SystemExit("This entrypoint is for LEDGERSYNC_PUBLIC_DEMO=1 only.")
    for command in ("migrate", "seed_public_demo", "flushexpiredtokens"):
        subprocess.run([sys.executable, str(backend / "manage.py"), command], check=True)
    os.execvp("gunicorn", [
        "gunicorn", "--chdir", str(backend), "config.wsgi:application",
        "--bind", f"0.0.0.0:{os.getenv('PORT', '10000')}",
        "--workers", "1", "--threads", "2", "--timeout", "120",
        "--access-logfile", "-", "--error-logfile", "-",
    ])
