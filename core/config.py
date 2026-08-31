"""Proje config dosyalarını (projects/<isim>/config.yaml) yükler ve
içindeki ${ENV_VAR} placeholder'larını ortam değişkenleriyle çözer."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = ROOT / "projects"

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _resolve_env(value: Any) -> Any:
    if isinstance(value, str):
        def _sub(m: re.Match) -> str:
            name = m.group(1)
            resolved = os.environ.get(name, "")
            return resolved
        return _ENV_PATTERN.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


@dataclass
class ProjectConfig:
    key: str
    raw: dict = field(repr=False)

    @property
    def display_name(self) -> str:
        return self.raw.get("display_name", self.key)

    @property
    def rss_sources(self) -> list[dict]:
        return self.raw.get("rss_sources", [])

    @property
    def instagram(self) -> dict:
        return self.raw.get("instagram", {})

    @property
    def llm(self) -> dict:
        return self.raw.get("llm", {})

    @property
    def image(self) -> dict:
        return self.raw.get("image", {})

    @property
    def filters(self) -> dict:
        return self.raw.get("filters", {})

    @property
    def state_csv_path(self) -> Path:
        return PROJECTS_DIR / self.key / "state.csv"

    @property
    def pending_json_path(self) -> Path:
        return PROJECTS_DIR / self.key / "pending.local.json"

    @property
    def sounds_dir(self) -> Path:
        """projects/<key>/sounds/*.mp3 — video arka plan sesleri için rastgele
        seçim havuzu. Klasör boş/yoksa video sessiz üretilir (bkz. video_gen.py)."""
        return PROJECTS_DIR / self.key / "sounds"

    @property
    def public_dir(self) -> Path:
        d = ROOT / "public" / self.key
        d.mkdir(parents=True, exist_ok=True)
        return d


def list_project_keys() -> list[str]:
    if not PROJECTS_DIR.exists():
        return []
    return sorted(
        p.name for p in PROJECTS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith("_") and (p / "config.yaml").exists()
    )


def load_project(key: str) -> ProjectConfig:
    path = PROJECTS_DIR / key / "config.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Proje config bulunamadı: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    raw = _resolve_env(raw)
    return ProjectConfig(key=key, raw=raw)
