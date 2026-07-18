"""
Load sources.yml from the project root.

Path resolution:
  This file lives at src/proxy_pool/utils/sources.py
  Going up 4 levels reaches the project root (where sources.yml sits).
"""
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SOURCES_FILE = _ROOT / "sources.yml"

def _load() -> dict:
    if not _SOURCES_FILE.exists():
        raise FileNotFoundError(f"sources.yml not found at {_SOURCES_FILE}")
    with open(_SOURCES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)

_data = _load()

def get(section: str, key: str) -> dict:
    """Return config dict for a single source, e.g. get('domestic', 'kuaidaili')."""
    return _data.get(section, {}).get(key, {})
