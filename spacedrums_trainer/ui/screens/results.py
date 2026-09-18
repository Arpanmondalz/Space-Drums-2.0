"""End-of-run summary, XP award, and the prompt to move on."""

from __future__ import annotations

import pygame

from ... import rhythms
from ...profile import XP_PER_LEVEL
from .. import theme, widgets
from ..app import Screen

PANEL = pygame.Rect(240, 118, 800, 430)


class ResultsScreen(Screen):
    def __init__(self, app, run, level_number=None):
        super().__init__(app)
        self.run = run
        self.level_number = level_number
        self.xp_gained = run.xp()
        self.shown_acc = 0.0
        self.shown_xp = 0.0
        self.age = 0.0

        self.next_level = None
        if level_number and level_number < len(rhythms.LEVELS):
            self.next_level = level_number + 1

        app.profile.record(run.rhythm.id, run.accuracy, self.xp_gained,
                           level_number, run.best_combo, run.hits)
        self.xp_before = max(0, app.profile.xp - self.xp_gained)

        labels = ["Play again"]
        if self.next_level:
            labels.insert(0, f"Level {self.next_level}")
        labels.append("Back")
        width = 224
        total = len(labels) * width + (len(labels) - 1) * 20
        x = PANEL.centerx - total // 2
        self.buttons = []
        for i, text in enumerate(labels):
            accent = theme.ACCENT if i == 0 else (138, 148, 176)
            self.buttons.append(widgets.Button((x + i * (width + 20), PANEL.bottom + 26, width, 64),
                                               text, "", accent, radius=16, compact=True))
        self.focus = 0
        self.buttons[0].focused = True
        self.mouse_down = False

    def on_enter(self):
        if self.app.scheduler:
            self.app.scheduler.clear()

    # ------------------------------------------------------------------
    def handle(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._back()
            elif event.key == pygame.K_RIGHT:
                self._move(1)
            elif event.key == pygame.K_LEFT:
                self._move(-1)
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._activate(self.focus)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.mouse_down = True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.mouse_down = False
            for i, b in enumerate(self.buttons):
                if b.rect.collidepoint(event.pos):
                    self._activate(i)

    def _move(self, delta):
        self.focus = (self.focus + delta) % len(self.buttons)
        for i, b in enumerate(self.buttons):
            b.focused = i == self.focus

    def _activate(self, index):
        from .play import PlayScreen

        text = self.buttons[index].title
        if text.startswith("Level"):
            number = self.next_level
            rhythm = rhythms.LEVELS[number - 1]
            self.app.replace(PlayScreen(self.app, rhythm,
                                        max(40, int(rhythm.target_bpm * 0.5)), number))
        elif text == "Play again":
            self.app.replace(PlayScreen(self.app, self.run.rhythm, self.run.start_bpm,
                                        self.level_number))
        else:
            self._back()

    def _back(self):
        self.app.pop()

    # ------------------------------------------------------------------
    def update(self, dt, t):
        self.age += dt
        self.shown_acc = theme.approach(self.shown_acc, self.run.accuracy, dt, 5.0)
        self.shown_xp = theme.approach(self.shown_xp, self.xp_gained, dt, 4.0)
        pos = pygame.mouse.get_pos()
        for b in self.buttons:
            b.update(dt, pos, self.mouse_down)

    def draw(self, dest):
        f, ov = self.app.fonts, self.app.overlay
        run = self.run
        widgets.draw_panel(dest, PANEL, 24)

        headline = "Level cleared" if (self.level_number and run.passed) else \
                   "Nice run" if run.passed else "Keep practising"
        ov.blit(f.render("ui", 11, headline.upper(), theme.TEXT_FAINT, tracking=3),
                (PANEL.x + 48, PANEL.y + 34))
        ov.blit(f.render("display", 32, run.rhythm.name, theme.TEXT, bold=True),
                (PANEL.x + 48, PANEL.y + 56))
        ov.blit(f.render("mono", 13, f"{run.start_bpm} to {run.target_bpm} BPM",
                         theme.TEXT_SOFT), (PANEL.x + 49, PANEL.y + 100))

        acc_color = theme.GOOD if run.passed else theme.WARN
        big = f.render("display", 78, f"{self.shown_acc:.0f}%", acc_color, bold=True)
        ov.blit(big, (PANEL.right - 72 - big.get_width(), PANEL.y + 44))
        widgets.stars(dest, (PANEL.right - 150, PANEL.y + 150), run.stars, size=14, gap=10)

        rows = [
            ("PERFECT", run.counts["PERFECT"], (150, 235, 255)),
            ("GOOD", run.counts["GOOD"], theme.GOOD),
            ("OK", run.counts["OK"], theme.WARN),
            ("MISSED", run.counts["MISS"], theme.BAD),
        ]
        y = PANEL.y + 168
        for name, count, color in rows:
            ov.blit(f.render("ui", 12, name, theme.TEXT_SOFT, tracking=2), (PANEL.x + 48, y))
            ov.blit(f.render("display", 18, str(count), color, bold=True), (PANEL.x + 176, y - 3))
            bar = (PANEL.x + 224, y + 5, 240, 8)
            frac = count / max(1, run.judged)
            widgets.progress_bar(dest, bar, frac, color, glow=False)
            y += 34

        delta = run.mean_delta_ms
        timing = ("Your timing is dead centre" if abs(delta) < 12 else
                  f"You are running {abs(delta):.0f} ms {'late' if delta > 0 else 'early'}")
        ov.blit(f.render("ui", 13, timing, theme.TEXT_SOFT), (PANEL.x + 48, y + 8))
        ov.blit(f.render("mono", 12, f"best combo {run.best_combo}    extra hits {run.ghosts}",
                         theme.TEXT_FAINT), (PANEL.x + 48, y + 32))

        xp_box = pygame.Rect(PANEL.right - 328, PANEL.bottom - 112, 280, 64)
        widgets.draw_panel(dest, xp_box, 14, (255, 255, 255, 7), (*theme.ACCENT, 60))
        ov.blit(f.render("ui", 11, "XP EARNED", theme.TEXT_FAINT, tracking=2),
                (xp_box.x + 18, xp_box.y + 12))
        ov.blit(f.render("display", 24, f"+{self.shown_xp:.0f}", theme.ACCENT, bold=True),
                (xp_box.x + 18, xp_box.y + 30))
        widgets.progress_bar(dest, (xp_box.x + 108, xp_box.y + 40, 152, 8),
                             self.app.profile.level_xp / XP_PER_LEVEL, theme.ACCENT)
        lvl = f.render("mono", 11, f"level {self.app.profile.level}", theme.TEXT_SOFT)
        ov.blit(lvl, (xp_box.x + 108, xp_box.y + 22))

        if self.level_number and not run.passed:
            note = f.render("ui", 13, "Under 65% - worth another go before you move on", theme.WARN)
            ov.blit(note, (PANEL.centerx - note.get_width() // 2, PANEL.bottom - 46))

        for b in self.buttons:
            b.draw(dest, ov, f)
