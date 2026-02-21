"""Runtime secret loading and canonical key resolution."""
from __future__ import annotations

from pathlib import Path
import os
from typing import Dict, Iterable, Optional, Tuple


SECRET_ALIASES: Dict[str, Tuple[str, ...]] = {
    "OPENAI_API_KEY": ("CHATGPT_API_KEY",),
    "ELEVENLABS_API_KEY": ("XI_API_KEY",),
    "PEXELS_API_KEY": (),
    "PIXABAY_API_KEY": (),
}


def _parse_env_file(env_path: Path) -> Dict[str, str]:
    if not env_path.exists():
        return {}
    parsed: Dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            parsed[key] = value
    return parsed


def get_secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    if direct:
        return direct
    for alias in SECRET_ALIASES.get(name, ()):
        candidate = os.getenv(alias, "").strip()
        if candidate:
            return candidate
    return ""


def load_env_and_bind(root: Path, override_existing: bool = False) -> Path:
    """Load .env into process and map aliases to canonical env names."""
    env_path = root / ".env"
    values = _parse_env_file(env_path)
    for key, value in values.items():
        current = os.getenv(key, "")
        if override_existing or not current:
            os.environ[key] = value

    for canonical, aliases in SECRET_ALIASES.items():
        if os.getenv(canonical, "").strip():
            continue
        for alias in aliases:
            alias_value = os.getenv(alias, "").strip()
            if alias_value:
                os.environ[canonical] = alias_value
                break
    return env_path


def missing_secrets(names: Iterable[str]) -> list[str]:
    return [name for name in names if not get_secret(name)]


def redact_secret(value: Optional[str]) -> str:
    token = (value or "").strip()
    if not token:
        return "<missing>"
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"
