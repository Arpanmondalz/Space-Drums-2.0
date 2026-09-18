"""Player progress: unlocked levels, best scores, XP."""

from __future__ import annotations

import json
import os
import time

from .config import CONFIG_DIR

PROFILE_PATH = os.path.join(CONFIG_DIR, "profile.json")

XP_PER_LEVEL = 600


class Profile:
    def __init__(self):
        self.xp = 0
        self.unlocked = 1          # highest level number the player may start
        self.bests: dict[str, float] = {}   # rhythm id -> best accuracy 0..100
        self.last_played = ""
        self.streak_day = ""
        self.streak = 0
        self.notes_hit = 0
        self.best_combo = 0
        self.load()

    # ------------------------------------------------------------------
    @property
    def level(self):
        return self.xp // XP_PER_LEVEL + 1

    @property
    def level_xp(self):
        return self.xp % XP_PER_LEVEL

    def best(self, rhythm_id):
        return self.bests.get(rhythm_id, 0.0)

    def stars(self, rhythm_id):
        acc = self.best(rhythm_id)
        return 3 if acc >= 92 else 2 if acc >= 80 else 1 if acc >= 65 else 0

    # ------------------------------------------------------------------
    def record(self, rhythm_id, accuracy, xp_gained, level_number=None, combo=0, hits=0):
        self.xp += max(0, int(xp_gained))
        self.notes_hit += hits
        self.best_combo = max(self.best_combo, combo)
        if accuracy > self.best(rhythm_id):
            self.bests[rhythm_id] = accuracy
        self.last_played = rhythm_id
        if level_number and accuracy >= 65:
            self.unlocked = max(self.unlocked, level_number + 1)
        self._touch_streak()
        self.save()

    def _touch_streak(self):
        today = time.strftime("%Y-%m-%d")
        if self.streak_day == today:
            return
        yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        self.streak = self.streak + 1 if self.streak_day == yesterday else 1
        self.streak_day = today

    # ------------------------------------------------------------------
    def load(self):
        try:
            with open(PROFILE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        for key in ("xp", "unlocked", "bests", "last_played", "streak_day",
                    "streak", "notes_hit", "best_combo"):
            if key in data:
                setattr(self, key, data[key])

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        payload = {k: getattr(self, k) for k in
                   ("xp", "unlocked", "bests", "last_played", "streak_day",
                    "streak", "notes_hit", "best_combo")}
        try:
            with open(PROFILE_PATH, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
        except OSError:
            pass
