"""Starting speed picker, shown before a Learn Rhythms run."""

from __future__ import annotations

import pygame

from ...session import Demo
from .. import theme, widgets
from ..app import Screen

PANEL = pygame.Rect(320, 200, 640, 320)
TRACK = pygame.Rect(PANEL.x + 56, 458, PANEL.w - 112, 10)


class BpmScreen(Screen):
    def __init__(self, app, rhythm):
        super().__init__(app)
        self.rhythm = rhythm
        self.floor = max(35, int(rhythm.target_bpm * 0.35))
        self.bpm = max(self.floor, int(rhythm.target_bpm * 0.55))
        self.preview: Demo | None = None
        self.back = widgets.BackButton((60, 26))

    def on_enter(self):
        self._stop_preview()

    # ------------------------------------------------------------------
    def handle(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._stop_preview()
                self.app.pop()
            elif event.key == pygame.K_LEFT:
                self._set(self.bpm - (5 if not self._shift() else 1))
            elif event.key == pygame.K_RIGHT:
                self._set(self.bpm + (5 if not self._shift() else 1))
            elif event.key == pygame.K_SPACE:
                self._toggle_preview()
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._start()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.back.clicked(event.pos):
                self._stop_preview()
                self.app.pop()
                return
            if TRACK.inflate(0, 28).collidepoint(event.pos):
                self._from_mouse(event.pos[0])
        elif event.type == pygame.MOUSEMOTION and event.buttons[0]:
            if TRACK.inflate(0, 40).collidepoint(event.pos):
                self._from_mouse(event.pos[0])

    @staticmethod
    def _shift():
        return pygame.key.get_mods() & pygame.KMOD_SHIFT

    def _from_mouse(self, x):
        frac = (x - TRACK.x) / TRACK.w
        self._set(round(self.floor + frac * (self.rhythm.target_bpm - self.floor)))

    def _set(self, value):
        self.bpm = max(self.floor, min(self.rhythm.target_bpm, int(value)))
        if self.preview:
            self._stop_preview()

    def _toggle_preview(self):
        if self.preview:
            self._stop_preview()
            return
        self.preview = Demo(self.app.kit, self.app.scheduler, self.rhythm, self.bpm)
        self.preview.start()

    def _stop_preview(self):
        if self.preview:
            self.preview.stop()
        self.preview = None
        if self.app.kit:
            self.app.kit.set_hat_closed(True)

    def _start(self):
        self._stop_preview()
        from .play import PlayScreen

        self.app.replace(PlayScreen(self.app, self.rhythm, self.bpm))

    # ------------------------------------------------------------------
    def update(self, dt, t):
        self.back.update(dt, pygame.mouse.get_pos())

    def draw(self, dest):
        f, ov = self.app.fonts, self.app.overlay
        self.back.draw(dest, ov, f)
        widgets.draw_panel(dest, PANEL, 22)
        theme.blit_glow(dest, theme.ACCENT, PANEL.center, PANEL.w * 0.7, 0.10)

        ov.blit(f.render("ui", 11, "STARTING SPEED", theme.TEXT_FAINT, tracking=3),
                (PANEL.x + 56, PANEL.y + 38))
        name = f.render("display", 30, self.rhythm.name, theme.TEXT, bold=True)
        ov.blit(name, (PANEL.x + 56, PANEL.y + 62))
        ov.blit(f.render("ui", 13, self.rhythm.blurb, theme.TEXT_SOFT), (PANEL.x + 56, PANEL.y + 100))

        big = f.render("display", 68, str(self.bpm), theme.ACCENT, bold=True)
        ov.blit(big, (PANEL.centerx - big.get_width() // 2, PANEL.y + 132))
        unit = f.render("ui", 13, "BPM", theme.TEXT_SOFT, tracking=3)
        ov.blit(unit, (PANEL.centerx - unit.get_width() // 2, PANEL.y + 210))

        frac = (self.bpm - self.floor) / max(1, self.rhythm.target_bpm - self.floor)
        widgets.progress_bar(dest, TRACK, frac, theme.ACCENT)
        knob = (int(TRACK.x + TRACK.w * frac), TRACK.centery)
        theme.blit_glow(dest, theme.ACCENT, knob, 40, 0.55)
        pygame.draw.circle(dest, (16, 20, 30), knob, 10)
        pygame.draw.circle(dest, theme.ACCENT, knob, 10, 2)

        ov.blit(f.render("mono", 12, str(self.floor), theme.TEXT_FAINT), (TRACK.x, TRACK.y + 22))
        target = f.render("mono", 12, f"{self.rhythm.target_bpm} target", theme.TEXT_FAINT)
        ov.blit(target, (TRACK.right - target.get_width(), TRACK.y + 22))

        note = (f"Starts at {self.bpm} BPM and climbs to {self.rhythm.target_bpm} BPM as you play.")
        surf = f.render("ui", 14, note, theme.TEXT_SOFT)
        ov.blit(surf, (PANEL.centerx - surf.get_width() // 2, PANEL.bottom + 26))

        widgets.key_hints(dest, ov, f, (640, 606),
                          [("ENTER", "start playing"), ("SPACE", "hear it"),
                           ("LEFT / RIGHT", "change speed"), ("ESC", "back")], align="center")
