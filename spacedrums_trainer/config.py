"""User settings, stored outside the repo so a git pull never clobbers them."""

from __future__ import annotations

import json
import os

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "spacedrums")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")

DEFAULTS = {
    "port": None,          # None = auto-detect
    "baud": 500000,
    "volume": 0.9,
    "input_offset_ms": 0,  # positive = your hits are reported late
    "metronome": True,
    "lookahead_s": 2.6,
}


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
            data.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return data


def save(data: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
