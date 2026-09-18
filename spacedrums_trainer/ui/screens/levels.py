"""Level select for Learn to Play."""

from __future__ import annotations

import pygame

from ... import rhythms
from ...session import Demo
from .. import theme, widgets
from ..app import Screen

COLS = 5
CARD_W, CARD_H, GAP_X, GAP_Y = 216, 112, 20, 18
GRID_X = (theme.LOGICAL_SIZE[0] - (COLS * CARD_W + (COLS - 1) * GAP_X)) // 2
GRID_Y = 152


class LevelSelectScreen(Screen):
    def __init__(self, app, focus=None):
        super().__init__(app)
        self.levels = rhythms.LEVELS
        self.focus = focus if focus is not None else min(len(self.levels), app.profile.unlocked) - 1
        self.hover = -1
        self.back = widgets.BackButton((GRID_X, 26))
        self.demo: Demo | None = None
        self.demo_index = -1

    def on_enter(self):
        self._stop_demo()

    def rect_for(self, index):
        col, row = index % COLS, index // COLS
        return pygame.Rect(GRID_X + col * (CARD_W + GAP_X), GRID_Y + row * (CARD_H + GAP_Y),
                           CARD_W, CARD_H)

    def listen_center(self, index):
        rect = self.rect_for(index)
        return rect.right - 26, rect.bottom - 26

    # ------------------------------------------------------------------
    def handle(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._stop_demo()
                self.app.pop()
            elif event.key == pygame.K_RIGHT:
                self.focus = min(len(self.levels) - 1, self.focus + 1)
            elif event.key == pygame.K_LEFT:
                self.focus = max(0, self.focus - 1)
            elif event.key == pygame.K_DOWN:
                self.focus = min(len(self.levels) - 1, self.focus + COLS)
            elif event.key == pygame.K_UP:
                self.focus = max(0, self.focus - COLS)
            elif event.key == pygame.K_SPACE:
                self._toggle_demo(self.focus)
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._start(self.focus)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.back.clicked(event.pos):
                self._stop_demo()
                self.app.pop()
                return
            for i in range(len(self.levels)):
                cx, cy = self.listen_center(i)
                if (event.pos[0] - cx) ** 2 + (event.pos[1] - cy) ** 2 <= 18 ** 2:
                    self.focus = i
                    self._toggle_demo(i)
                    return
            for i in range(len(self.levels)):
                if self.rect_for(i).collidepoint(event.pos):
                    self.focus = i
                    self._start(i)

    def _toggle_demo(self, index):
        if self.demo_index == index:
            self._stop_demo()
            return
        self._stop_demo()
        rhythm = self.levels[index]
        self.demo = Demo(self.app.kit, self.app.scheduler, rhythm, int(rhythm.target_bpm * 0.8))
        self.demo.start()
        self.demo_index = index

    def _stop_demo(self):
        if self.demo:
            self.demo.stop()
        self.demo = None
        self.demo_index = -1
        if self.app.kit:
            self.app.kit.set_hat_closed(True)

    def _start(self, index):
        self._stop_demo()
        from .play import PlayScreen

        rhythm = self.levels[index]
        start_bpm = max(40, int(rhythm.target_bpm * 0.5))
        self.app.push(PlayScreen(self.app, rhythm, start_bpm, level_number=index + 1))

    # ------------------------------------------------------------------
    def update(self, dt, t):
        pos = pygame.mouse.get_pos()
        self.back.update(dt, pos)
        self.hover = next((i for i in range(len(self.levels))
                           if self.rect_for(i).collidepoint(pos)), -1)

    def draw(self, dest):
        f, ov = self.app.fonts, self.app.overlay
        profile = self.app.profile

        self.back.draw(dest, ov, f)
        ov.blit(f.render("display", 34, "Learn to Play", theme.TEXT, bold=True), (GRID_X + 148, 28))

        shown = self.levels[self.hover if self.hover >= 0 else self.focus]
        number = self.levels.index(shown) + 1
        ov.blit(f.render("ui", 14, f"Level {number}   {shown.name}", theme.ACCENT), (GRID_X, 84))
        ov.blit(f.render("ui", 14, shown.blurb, theme.TEXT_SOFT), (GRID_X, 108))
        for i, rhythm in enumerate(self.levels):
            self._card(dest, ov, f, i, rhythm, profile)

        widgets.key_hints(dest, ov, f, (640, 668),
                          [("ENTER", "start"), ("SPACE", "listen"), ("ARROWS", "move"),
                           ("ESC", "back")], align="center")

    def _card(self, dest, ov, f, index, rhythm, profile):
        rect = self.rect_for(index)
        active = index == self.focus or index == self.hover
        playing = index == self.demo_index
        stars = profile.stars(rhythm.id)
        accent = theme.GOOD if playing else theme.GOOD if stars == 3 else theme.ACCENT

        if active or playing:
            theme.blit_glow(dest, accent, rect.center, rect.w * 0.8, 0.26)
        widgets.draw_panel(dest, rect, 16, (255, 255, 255, 16 if active else 8),
                           (*accent, 150 if (active or playing) else 34))

        badge = (rect.x + 32, rect.y + 32)
        pygame.draw.circle(dest, (26, 32, 48), badge, 19)
        pygame.draw.circle(dest, accent, badge, 19, 2)
        num = f.render("display", 17, str(index + 1), theme.TEXT, bold=True)
        ov.blit(num, (badge[0] - num.get_width() // 2, badge[1] - num.get_height() // 2))

        ov.blit(f.render("display", 17, rhythm.name, theme.TEXT, bold=True),
                (rect.x + 60, rect.y + 16))
        best = profile.best(rhythm.id)
        meta = f"{rhythm.target_bpm} BPM" + (f"    best {best:.0f}%" if best > 0 else "")
        ov.blit(f.render("mono", 11, meta, theme.TEXT_FAINT), (rect.x + 60, rect.y + 40))

        self._listen_button(dest, index, playing, active)
        widgets.stars(dest, (rect.x + 32, rect.bottom - 26), stars, size=9, gap=5)

    def _listen_button(self, dest, index, playing, active):
        cx, cy = self.listen_center(index)
        color = theme.GOOD if playing else (theme.TEXT_SOFT if active else theme.TEXT_FAINT)
        if playing:
            theme.blit_glow(dest, color, (cx, cy), 46, 0.45)
        pygame.draw.circle(dest, color, (cx, cy), 14, 1)
        if playing:
            pygame.draw.rect(dest, color, (cx - 5, cy - 5, 4, 10))
            pygame.draw.rect(dest, color, (cx + 1, cy - 5, 4, 10))
        else:
            pygame.draw.polygon(dest, color, [(cx - 4, cy - 6), (cx + 6, cy), (cx - 4, cy + 6)])
