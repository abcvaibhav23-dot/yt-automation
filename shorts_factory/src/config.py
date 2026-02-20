"""Configuration and path utilities for Shorts Factory."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    """Absolute paths used by the application."""

    root: Path
    scripts: Path
    audio: Path
    assets: Path
    output: Path
    logs: Path

    @classmethod
    def discover(cls) -> "AppPaths":
        # src/config.py -> src -> shorts_factory root
        root = Path(__file__).resolve().parents[1]
        return cls(
            root=root,
            scripts=root / "scripts",
            audio=root / "audio",
            assets=root / "assets",
            output=root / "output",
            logs=root / "logs",
        )

    def ensure_directories(self) -> None:
        for folder in [self.scripts, self.audio, self.assets, self.output, self.logs]:
            folder.mkdir(parents=True, exist_ok=True)


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
