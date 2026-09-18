"""Learn Rhythms: browse grooves, listen to them, then pick one to practise."""

from __future__ import annotations

import pygame

from ... import rhythms
from ...session import Demo
from .. import theme, widgets
from ..app import Screen
from ..theme import LANES

ROW_X, ROW_W, ROW_H, ROW_GAP = 150, 980, 64, 9
ROW_Y = 146


class LibraryScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.grooves = rhythms.GROOVES
        self.focus = 0
        self.hover = -1
        self.demo: Demo | None = None
        self.demo_index = -1
        self.back = widgets.BackButton((ROW_X, 26))

    def on_enter(self):
        self._stop_demo()

    def rect_for(self, index):
        return pygame.Rect(ROW_X, ROW_Y + index * (ROW_H + ROW_GAP), ROW_W, ROW_H)

    # ------------------------------------------------------------------
    def handle(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._stop_demo()
                self.app.pop()
            elif event.key == pygame.K_DOWN:
                self.focus = (self.focus + 1) % len(self.grooves)
            elif event.key == pygame.K_UP:
                self.focus = (self.focus - 1) % len(self.grooves)
            elif event.key == pygame.K_SPACE:
                self._toggle_demo(self.focus)
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._learn(self.focus)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.back.clicked(event.pos):
                self._stop_demo()
                self.app.pop()
                return
            for i in range(len(self.grooves)):
                rect = self.rect_for(i)
                if not rect.collidepoint(event.pos):
                    continue
                self.focus = i
                if event.pos[0] > rect.right - 130:
                    self._learn(i)
                elif event.pos[0] > rect.right - 258:
                    self._toggle_demo(i)

    # ------------------------------------------------------------------
    def _toggle_demo(self, index):
        if self.demo_index == index:
            self._stop_demo()
            return
        self._stop_demo()
        groove = self.grooves[index]
        # Demo at a comfortable listening speed, not full tempo.
        self.demo = Demo(self.app.kit, self.app.scheduler, groove,
                         int(groove.target_bpm * 0.8))
        self.demo.start()
        self.demo_index = index

    def _stop_demo(self):
        if self.demo:
            self.demo.stop()
        self.demo = None
        self.demo_index = -1
        if self.app.kit:
            self.app.kit.set_hat_closed(True)

    def _learn(self, index):
        self._stop_demo()
        from .bpm import BpmScreen

        self.app.push(BpmScreen(self.app, self.grooves[index]))

    # ------------------------------------------------------------------
    def update(self, dt, t):
        pos = pygame.mouse.get_pos()
        self.back.update(dt, pos)
        self.hover = next((i for i in range(len(self.grooves))
                           if self.rect_for(i).collidepoint(pos)), -1)

    def draw(self, dest):
        f, ov = self.app.fonts, self.app.overlay
        self.back.draw(dest, ov, f)
        ov.blit(f.render("display", 34, "Learn Rhythms", theme.TEXT, bold=True), (ROW_X + 148, 28))
        ov.blit(f.render("ui", 14, "Listen to a groove first. When you like one, pick your "
                                   "starting speed and play along.", theme.TEXT_SOFT),
                (ROW_X, 92))

        for i, groove in enumerate(self.grooves):
            self._row(dest, ov, f, i, groove)

        widgets.key_hints(dest, ov, f, (640, 668),
                          [("ENTER", "learn this groove"), ("SPACE", "listen"), ("ESC", "back")],
                          align="center")

    def _row(self, dest, ov, f, index, groove):
        rect = self.rect_for(index)
        active = index == self.focus or index == self.hover
        playing = index == self.demo_index
        accent = theme.GOOD if playing else theme.ACCENT

        if active:
            theme.blit_glow(dest, accent, rect.center, rect.w * 0.45, 0.14)
        widgets.draw_panel(dest, rect, 14, (255, 255, 255, 15 if active else 7),
                           (*accent, 130 if active else 28))

        ov.blit(f.render("display", 19, groove.name, theme.TEXT, bold=True),
                (rect.x + 24, rect.y + 10))
        ov.blit(f.render("ui", 13, groove.blurb, theme.TEXT_SOFT), (rect.x + 24, rect.y + 36))

        # Voice dots show at a glance which limbs the groove asks for.
        vx = rect.x + 430
        for drum in sorted(groove.voices()):
            if drum in LANES:
                pygame.draw.circle(dest, theme.NEUTRAL, (vx, rect.centery), 5)
            else:
                widgets.capsule(dest, (vx - 7, rect.centery - 3, 14, 6), theme.FOOT)
            vx += 18

        ov.blit(f.render("mono", 12, f"{groove.target_bpm} BPM", theme.TEXT_FAINT),
                (rect.x + 560, rect.centery - 7))
        widgets.stars(dest, (rect.x + 654, rect.centery), self.app.profile.stars(groove.id),
                      size=8, gap=4)

        self._pill(dest, ov, f, (rect.right - 252, rect.centery - 16, 118, 32),
                   "STOP" if playing else "LISTEN", accent, playing)
        self._pill(dest, ov, f, (rect.right - 124, rect.centery - 16, 100, 32),
                   "LEARN", theme.ACCENT, active)

    def _pill(self, dest, ov, f, rect, text, color, filled):
        widgets.capsule(dest, rect, color, 190 if filled else 40)
        label = f.render("ui", 12, text, (16, 20, 30) if filled else color, tracking=2)
        ov.blit(label, (rect[0] + (rect[2] - label.get_width()) // 2,
                        rect[1] + (rect[3] - label.get_height()) // 2))
