"""Application shell: window setup, screen stack, cross-fade transitions."""

from __future__ import annotations

import time

import pygame

from . import fx, theme


class Screen:
    def __init__(self, app: "App"):
        self.app = app

    def on_enter(self):
        pass

    def handle(self, event: pygame.event.Event):
        pass

    def update(self, dt: float, t: float):
        pass

    def draw(self, dest: pygame.Surface):
        """Shapes go to `dest`; text goes to `self.app.overlay` so bloom can't blur it."""
        pass


class App:
    def __init__(self, fullscreen=False, bloom=True):
        pygame.init()
        pygame.display.set_caption("Space Drums")

        flags = pygame.SCALED | (pygame.FULLSCREEN if fullscreen else 0)
        self.window = pygame.display.set_mode(theme.LOGICAL_SIZE, flags, vsync=1)
        self.fullscreen = fullscreen

        self.canvas = pygame.Surface(theme.LOGICAL_SIZE)
        self.overlay = pygame.Surface(theme.LOGICAL_SIZE, pygame.SRCALPHA)
        self.layer = pygame.Surface(theme.LOGICAL_SIZE, pygame.SRCALPHA)
        self.fonts = theme.fonts()
        self.background = fx.Background()
        self.bloom = fx.Bloom()
        self.bloom_on = bloom
        self.show_stats = False

        self.clock = pygame.time.Clock()
        self.t0 = time.perf_counter()
        self.stack: list[Screen] = []
        self.running = True

        # Wired up by __main__ once the audio and serial layers exist.
        self.kit = None
        self.hub = None
        self.scheduler = None
        self.profile = None
        self.settings: dict = {}

        self._toast = ""
        self._toast_life = 0.0
        self._fade: pygame.Surface | None = None
        self._fade_life = 0.0
        self._fade_total = 0.28
        self._frame_ms = 0.0

    # ------------------------------------------------------------------
    def push(self, screen: Screen):
        self._snapshot()
        self.stack.append(screen)
        screen.on_enter()

    def pop(self):
        if len(self.stack) > 1:
            self._snapshot()
            self.stack.pop()
            self.stack[-1].on_enter()
        else:
            self.running = False

    def _snapshot(self):
        if not self.stack:
            return
        self.layer.fill((0, 0, 0, 0))
        prev, self.overlay = self.overlay, self.layer
        self.stack[-1].draw(self.layer)
        self.overlay = prev
        if self._fade is None:
            self._fade = pygame.Surface(theme.LOGICAL_SIZE, pygame.SRCALPHA)
        self._fade.fill((0, 0, 0, 0))
        self._fade.blit(self.layer, (0, 0))
        self._fade_life = self._fade_total

    def toast(self, message, seconds=2.6):
        self._toast = message
        self._toast_life = seconds

    def replace(self, screen: Screen):
        self._snapshot()
        if self.stack:
            self.stack.pop()
        self.stack.append(screen)
        screen.on_enter()

    def reset_to(self, screen: Screen):
        self._snapshot()
        self.stack = [screen]
        screen.on_enter()

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        flags = pygame.SCALED | (pygame.FULLSCREEN if self.fullscreen else 0)
        self.window = pygame.display.set_mode(theme.LOGICAL_SIZE, flags, vsync=1)

    # ------------------------------------------------------------------
    def run(self):
        while self.running:
            dt = min(0.05, self.clock.tick(60) / 1000.0)
            t = time.perf_counter() - self.t0
            frame_start = time.perf_counter()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    self.toggle_fullscreen()
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F3:
                    self.show_stats = not self.show_stats
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_b:
                    self.bloom_on = not self.bloom_on
                elif self.stack:
                    self.stack[-1].handle(event)

            self.background.update(dt)
            if self.stack:
                self.stack[-1].update(dt, t)
            if self._fade_life > 0:
                self._fade_life -= dt

            self.overlay.fill((0, 0, 0, 0))
            self.background.draw(self.canvas, t)
            if self.stack:
                self.stack[-1].draw(self.canvas)

            if self.bloom_on:
                self.bloom.apply(self.canvas)
            self.canvas.blit(self.overlay, (0, 0))

            if self._fade is not None and self._fade_life > 0:
                k = self._fade_life / self._fade_total
                self._fade.set_alpha(int(255 * theme.ease_out(k)))
                self.canvas.blit(self._fade, (0, int((1 - k) * -18)))

            if self._toast_life > 0:
                self._toast_life -= dt
                self._draw_toast()

            if self.show_stats:
                self._draw_stats()

            self.window.blit(self.canvas, (0, 0))
            pygame.display.flip()
            self._frame_ms = theme.approach(self._frame_ms,
                                            (time.perf_counter() - frame_start) * 1000.0, dt, 6.0)

        self._teardown()

    def _teardown(self):
        # Stop the worker threads first: a metronome click or an incoming hit
        # must never reach a mixer that pygame.quit() has already torn down.
        for service in (self.hub, self.scheduler):
            if service is not None:
                service.shutdown()
        try:
            pygame.mixer.stop()
        except pygame.error:
            pass
        pygame.quit()

    def _draw_stats(self):
        text = (f"{self.clock.get_fps():5.1f} fps   cpu {self._frame_ms:4.1f} ms   "
                f"bloom {'on' if self.bloom_on else 'off'}   "
                f"glow sprites {len(theme._GLOW_CACHE)}")
        surf = self.fonts.render("mono", 13, text, theme.TEXT_SOFT)
        self.canvas.blit(surf, (16, theme.LOGICAL_SIZE[1] - 24))

    def _draw_toast(self):
        label = self.fonts.render("ui", 15, self._toast, theme.TEXT)
        w, h = label.get_width() + 48, 44
        x, y = (theme.LOGICAL_SIZE[0] - w) // 2, theme.LOGICAL_SIZE[1] - 116
        alpha = int(255 * min(1.0, self._toast_life / 0.4))
        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (22, 26, 38, 232), (0, 0, w, h), border_radius=12)
        pygame.draw.rect(panel, (*theme.ACCENT, 120), (0, 0, w, h), width=1, border_radius=12)
        panel.blit(label, (24, (h - label.get_height()) // 2))
        panel.set_alpha(alpha)
        self.canvas.blit(panel, (x, y))
