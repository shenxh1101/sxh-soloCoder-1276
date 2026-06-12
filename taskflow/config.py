from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".taskflow"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class Config:
    theme: str = "dracula"
    sync_method: str = "none"
    sync_url: str = ""
    pomodoro_duration: int = 25
    pomodoro_break: int = 5
    pomodoro_long_break: int = 15
    default_view: str = "list"
    language: str = "zh"


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        return Config()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return Config(**{k: v for k, v in data.items() if k in Config.__dataclass_fields__})
    except (json.JSONDecodeError, TypeError):
        return Config()


def save_config(config: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(asdict(config), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_db_path() -> Path:
    return CONFIG_DIR / "taskflow.db"
