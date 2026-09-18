"""Home: three modes, player card, stick batteries, hub status."""

from __future__ import annotations

import math
import time

import pygame

from .. import theme, widgets
from ..app import Screen

CARD_Y, CARD_H, CARD_W, CARD_GAP = 232, 226, 368, 28
BATTERY = pygame.Rect(60, 492, 556, 124)
STICKS = {0: "LEFT STICK", 1: "RIGHT STICK"}
LOW_PCT = 20


class HomeScreen(Screen):
    def __init__(self, app):
        super().__init__(app)
        self.buttons = [
            widgets.Button((60, CARD_Y, CARD_W, CARD_H), "Learn to Play",
                           "Numbered levels, one groove each", theme.ACCENT, widgets.icon_rhythm),
            widgets.Button((60 + CARD_W + CARD_GAP, CARD_Y, CARD_W, CARD_H), "Learn Rhythms",
                           "Listen first, then play along", theme.GOOD, widgets.icon_kit),
            widgets.Button((60 + 2 * (CARD_W + CARD_GAP), CARD_Y, CARD_W, CARD_H), "Custom Rhythms",
                           "Import a MIDI drum track", (138, 148, 176), widgets.icon_gear),
        ]
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
                self.app.running = False
            elif event.key in (pygame.K_RIGHT, pygame.K_TAB):
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
        if index == 0:
            from .levels import LevelSelectScreen

            self.app.push(LevelSelectScreen(self.app))
        elif index == 1:
            from .library import LibraryScreen

            self.app.push(LibraryScreen(self.app))
        else:
            self.app.toast("Custom MIDI rhythms are coming soon")

    # ------------------------------------------------------------------
    def update(self, dt, t):
        pos = pygame.mouse.get_pos()
        for b in self.buttons:
            b.update(dt, pos, self.mouse_down)

    def draw(self, dest):
        f = self.app.fonts
        ov = self.app.overlay
        ov.blit(f.render("display", 44, "SPACE DRUMS", theme.TEXT, bold=True, tracking=3), (60, 52))
        ov.blit(f.render("ui", 12, "A I R   D R U M   T R A I N E R", theme.TEXT_FAINT, tracking=2),
                (63, 104))

        self._player_card(dest, ov, f)
        for b in self.buttons:
            b.draw(dest, ov, f)
        self._battery_panel(dest, ov, f)
        self._footer(dest, ov, f)

        soon = self.buttons[2].rect
        widgets.capsule(dest, (soon.right - 132, soon.y + 22, 112, 24), (150, 160, 190), 40)
        ov.blit(f.render("ui", 10, "COMING SOON", theme.TEXT_SOFT, tracking=2),
                (soon.right - 122, soon.y + 28))

    # ------------------------------------------------------------------
    def _player_card(self, dest, ov, f):
        profile = self.app.profile
        rect = pygame.Rect(812, 48, 408, 96)
        widgets.draw_panel(dest, rect, 20)

        cx, cy = rect.x + 54, rect.centery
        theme.blit_glow(dest, theme.ACCENT, (cx, cy), 64, 0.42)
        pygame.draw.circle(dest, (26, 34, 52), (cx, cy), 29)
        pygame.draw.circle(dest, theme.ACCENT, (cx, cy), 29, 2)
        num = f.render("display", 28, str(profile.level), theme.TEXT, bold=True)
        ov.blit(num, (cx - num.get_width() // 2, cy - num.get_height() // 2 - 1))

        ov.blit(f.render("ui", 11, "LEVEL", theme.TEXT_FAINT, tracking=2), (rect.x + 98, rect.y + 24))
        from ...profile import XP_PER_LEVEL

        widgets.progress_bar(dest, (rect.x + 98, rect.y + 46, 196, 8),
                             profile.level_xp / XP_PER_LEVEL, theme.ACCENT)
        ov.blit(f.render("mono", 12, f"{profile.level_xp} / {XP_PER_LEVEL} XP", theme.TEXT_SOFT),
                (rect.x + 98, rect.y + 60))

        badge = pygame.Rect(rect.right - 108, rect.y + 44, 88, 32)
        ov.blit(f.render("ui", 11, "STREAK", theme.TEXT_FAINT, tracking=2), (badge.x + 6, rect.y + 24))
        widgets.capsule(dest, badge, theme.FOOT, 34)
        streak = f.render("display", 18, f"{profile.streak} d", theme.FOOT, bold=True)
        ov.blit(streak, (badge.centerx - streak.get_width() // 2,
                         badge.centery - streak.get_height() // 2))

    def _battery_panel(self, dest, ov, f):
        widgets.draw_panel(dest, BATTERY, 18)
        ov.blit(f.render("ui", 11, "STICK BATTERIES", theme.TEXT_FAINT, tracking=3),
                (BATTERY.x + 24, BATTERY.y + 18))

        hub = self.app.hub
        now = time.time()
        for i, stick_id in enumerate((0, 1)):
            y = BATTERY.y + 50 + i * 38
            color = theme.STICK_LEFT if stick_id == 0 else theme.STICK_RIGHT
            ov.blit(f.render("ui", 12, STICKS[stick_id], color, tracking=1), (BATTERY.x + 24, y + 1))

            bar = pygame.Rect(BATTERY.x + 170, y, 240, 14)
            widgets.capsule(dest, bar, (255, 255, 255), 22)

            state = hub.battery.get(stick_id) if hub else None
            if state is None:
                ov.blit(f.render("mono", 12, "no report yet", theme.TEXT_FAINT), (bar.right + 16, y + 1))
                continue

            stale = now - state["time"] > 60
            pct = state["pct"]
            tint = (theme.TEXT_FAINT if stale else
                    theme.BAD if pct <= LOW_PCT else theme.WARN if pct <= 45 else theme.GOOD)
            widgets.capsule(dest, (bar.x, bar.y, max(6, int(bar.w * pct / 100)), bar.h), tint)
            label = f"{pct:3d}%   {state['mv'] / 1000:.2f} V" + ("   old" if stale else "")
            ov.blit(f.render("mono", 12, label, tint), (bar.right + 16, y + 1))

    def _footer(self, dest, ov, f):
        y = 664
        hub = self.app.hub
        ok = bool(hub and hub.connected)
        color = theme.GOOD if ok else theme.WARN
        pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 420.0)
        theme.blit_glow(dest, color, (72, y + 8), 22, 0.35 + 0.35 * pulse)
        pygame.draw.circle(dest, color, (72, y + 8), 4)
        ov.blit(f.render("mono", 13, hub.status if hub else "No hub", theme.TEXT_SOFT), (88, y))

        widgets.key_hints(dest, ov, f, (1220, y - 5),
                          [("ENTER", "choose"), ("F11", "fullscreen"), ("ESC", "quit")],
                          align="right")
