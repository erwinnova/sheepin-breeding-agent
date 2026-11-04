"""
Loads KEY=value lines from a .env file for local runs, without extra dependencies.
"""
import os
from pathlib import Path


def load_env() -> str | None:
    here = Path(__file__).resolve().parent
    for path in (here / ".env", here.parent / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():   # utf-8-sig: tolerate Notepad BOM
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
        return str(path)
    return None


ENV_FILE = load_env()