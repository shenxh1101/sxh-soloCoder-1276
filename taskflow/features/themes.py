from __future__ import annotations

import json
from pathlib import Path
from typing import Any

THEMES_DIR = Path.home() / ".taskflow" / "themes"

BUILT_IN_THEMES: dict[str, dict[str, Any]] = {
    "dracula": {
        "bg": "#282a36",
        "fg": "#f8f8f2",
        "accent": "#bd93f9",
        "accent2": "#ff79c6",
        "success": "#50fa7b",
        "warning": "#f1fa8c",
        "error": "#ff5555",
        "muted": "#6272a4",
        "highlight": "#44475a",
        "panel_border": "#6272a4",
        "project_color": "#8be9fd",
        "tag_colors": [
            "#ff79c6",
            "#bd93f9",
            "#50fa7b",
            "#f1fa8c",
            "#8be9fd",
            "#ffb86c",
            "#ff5555",
            "#6272a4",
        ],
        "priority_colors": {
            "urgent_important": "#ff5555",
            "not_urgent_important": "#f1fa8c",
            "urgent_not_important": "#ffb86c",
            "not_urgent_not_important": "#6272a4",
        },
    },
    "solarized": {
        "bg": "#002b36",
        "fg": "#839496",
        "accent": "#268bd2",
        "accent2": "#d33682",
        "success": "#859900",
        "warning": "#b58900",
        "error": "#dc322f",
        "muted": "#586e75",
        "highlight": "#073642",
        "panel_border": "#586e75",
        "project_color": "#2aa198",
        "tag_colors": [
            "#268bd2",
            "#d33682",
            "#859900",
            "#b58900",
            "#2aa198",
            "#cb4b16",
            "#dc322f",
            "#6c71c4",
        ],
        "priority_colors": {
            "urgent_important": "#dc322f",
            "not_urgent_important": "#b58900",
            "urgent_not_important": "#cb4b16",
            "not_urgent_not_important": "#586e75",
        },
    },
    "nord": {
        "bg": "#2e3440",
        "fg": "#d8dee9",
        "accent": "#88c0d0",
        "accent2": "#b48ead",
        "success": "#a3be8c",
        "warning": "#ebcb8b",
        "error": "#bf616a",
        "muted": "#4c566a",
        "highlight": "#3b4252",
        "panel_border": "#4c566a",
        "project_color": "#81a1c1",
        "tag_colors": [
            "#88c0d0",
            "#b48ead",
            "#a3be8c",
            "#ebcb8b",
            "#81a1c1",
            "#d08770",
            "#bf616a",
            "#5e81ac",
        ],
        "priority_colors": {
            "urgent_important": "#bf616a",
            "not_urgent_important": "#ebcb8b",
            "urgent_not_important": "#d08770",
            "not_urgent_not_important": "#4c566a",
        },
    },
    "gruvbox": {
        "bg": "#282828",
        "fg": "#ebdbb2",
        "accent": "#fe8019",
        "accent2": "#d3869b",
        "success": "#b8bb26",
        "warning": "#fabd2f",
        "error": "#fb4934",
        "muted": "#665c54",
        "highlight": "#3c3836",
        "panel_border": "#665c54",
        "project_color": "#83a598",
        "tag_colors": [
            "#fe8019",
            "#d3869b",
            "#b8bb26",
            "#fabd2f",
            "#83a598",
            "#d65d0e",
            "#fb4934",
            "#8ec07c",
        ],
        "priority_colors": {
            "urgent_important": "#fb4934",
            "not_urgent_important": "#fabd2f",
            "urgent_not_important": "#d65d0e",
            "not_urgent_not_important": "#665c54",
        },
    },
    "monokai": {
        "bg": "#272822",
        "fg": "#f8f8f2",
        "accent": "#a6e22e",
        "accent2": "#fd971f",
        "success": "#a6e22e",
        "warning": "#e6db74",
        "error": "#f92672",
        "muted": "#75715e",
        "highlight": "#3e3d32",
        "panel_border": "#75715e",
        "project_color": "#66d9ef",
        "tag_colors": [
            "#f92672",
            "#a6e22e",
            "#e6db74",
            "#66d9ef",
            "#fd971f",
            "#ae81ff",
            "#f4bf75",
            "#75715e",
        ],
        "priority_colors": {
            "urgent_important": "#f92672",
            "not_urgent_important": "#e6db74",
            "urgent_not_important": "#fd971f",
            "not_urgent_not_important": "#75715e",
        },
    },
}

_REQUIRED_KEYS = {
    "bg", "fg", "accent", "accent2", "success", "warning", "error",
    "muted", "highlight", "panel_border", "project_color",
    "tag_colors", "priority_colors",
}

_PRIORITY_KEYS = {
    "urgent_important",
    "not_urgent_important",
    "urgent_not_important",
    "not_urgent_not_important",
}


def _validate_theme(data: dict[str, Any]) -> None:
    missing = _REQUIRED_KEYS - set(data.keys())
    if missing:
        raise ValueError(f"Theme missing keys: {missing}")
    if not isinstance(data["tag_colors"], list) or len(data["tag_colors"]) < 8:
        raise ValueError("Theme tag_colors must be a list of at least 8 colors")
    prio_keys = set(data["priority_colors"].keys())
    missing_prio = _PRIORITY_KEYS - prio_keys
    if missing_prio:
        raise ValueError(f"Theme priority_colors missing keys: {missing_prio}")


class Theme:
    def __init__(self, data: dict[str, Any]) -> None:
        _validate_theme(data)
        self._data = data

    @property
    def bg(self) -> str:
        return self._data["bg"]

    @property
    def fg(self) -> str:
        return self._data["fg"]

    @property
    def accent(self) -> str:
        return self._data["accent"]

    @property
    def accent2(self) -> str:
        return self._data["accent2"]

    @property
    def success(self) -> str:
        return self._data["success"]

    @property
    def warning(self) -> str:
        return self._data["warning"]

    @property
    def error(self) -> str:
        return self._data["error"]

    @property
    def muted(self) -> str:
        return self._data["muted"]

    @property
    def highlight(self) -> str:
        return self._data["highlight"]

    @property
    def panel_border(self) -> str:
        return self._data["panel_border"]

    @property
    def project_color(self) -> str:
        return self._data["project_color"]

    @property
    def tag_colors(self) -> list[str]:
        return self._data["tag_colors"]

    @property
    def priority_colors(self) -> dict[str, str]:
        return self._data["priority_colors"]

    def raw(self) -> dict[str, Any]:
        return dict(self._data)


def get_theme(name: str) -> Theme:
    if name in BUILT_IN_THEMES:
        return Theme(BUILT_IN_THEMES[name])
    custom_path = THEMES_DIR / f"{name}.json"
    if custom_path.exists():
        data = json.loads(custom_path.read_text(encoding="utf-8"))
        return Theme(data)
    raise ValueError(f"Unknown theme: {name}")


def list_themes() -> list[str]:
    names = list(BUILT_IN_THEMES.keys())
    if THEMES_DIR.exists():
        for f in THEMES_DIR.iterdir():
            if f.suffix == ".json":
                names.append(f.stem)
    return names
