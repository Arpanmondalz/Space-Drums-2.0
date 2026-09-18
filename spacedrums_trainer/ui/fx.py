"""Background, particles, shockwaves and bloom.

All of these are additive blits of pre-rendered sprites; no surface is
allocated inside the frame loop.
"""

from __future__ import annotations

import math
import random

import pygame

from . import theme


class Background:
    """Gradient base + slowly drifting aurora blobs + vignette."""

    def __init__(self, size=theme.LOGICAL_SIZE):
        self.size = size
        self.base = theme.vertical_gradient(size, theme.BG_TOP, theme.BG_BOTTOM)
        self.vignette = self._make_vignette(size, 118)
        self.blobs = [
            (theme.make_glow(color, diameter, intensity), diameter, speed, phase)
            for color, diameter, intensity, speed, phase in theme.AURORA
        ]
        self.pulse = 0.0

    @staticmethod
    def _make_vignette(size, strength):
        surf = pygame.Surface(size, pygame.SRCALPHA)
        surf.fill((0, 0, 0, strength))
        w, h = size
        steps = 72
        for i in range(steps):
            t = (i + 1) / steps
            rw = int(w * 1.55 * (1.0 - t * 0.97))
            rh = int(h * 1.55 * (1.0 - t * 0.97))
            alpha = int(strength * (1.0 - t) ** 1.25)
            pygame.draw.ellipse(surf, (0, 0, 0, alpha), (w // 2 - rw // 2, h // 2 - rh // 2, rw, rh))
        return surf

    def kick(self, amount=1.0):
        self.pulse = min(1.4, self.pulse + amount)

    def update(self, dt):
        self.pulse = max(0.0, self.pulse - dt * 2.6)

    def draw(self, dest, t):
        dest.blit(self.base, (0, 0))
        w, h = self.size
        for sprite, diameter, speed, phase in self.blobs:
            a = t * speed + phase
            x = w * (0.5 + 0.34 * math.sin(a)) - diameter / 2
            y = h * (0.46 + 0.30 * math.cos(a * 0.77 + 1.1)) - diameter / 2
            dest.blit(sprite, (int(x), int(y)), special_flags=pygame.BLEND_ADD)
        if self.pulse > 0.01:
            k = theme.ease_out(min(1.0, self.pulse)) * 26
            dest.fill((int(k * 0.5), int(k * 0.55), int(k)), special_flags=pygame.BLEND_ADD)
        dest.blit(self.vignette, (0, 0))


class Particles:
    """Fixed-budget additive sparks."""

    __slots__ = ("items", "limit")

    def __init__(self, limit=280):
        self.items = []
        self.limit = limit

    def burst(self, pos, color, count=14, speed=260, spread=math.pi, direction=-math.pi / 2, life=0.55):
        room = self.limit - len(self.items)
        if room <= 0:
            return
        for _ in range(min(count, room)):
            angle = direction + random.uniform(-spread, spread) * 0.5
            v = speed * random.uniform(0.25, 1.0)
            self.items.append(
                [pos[0], pos[1], math.cos(angle) * v, math.sin(angle) * v,
                 life * random.uniform(0.6, 1.0), life * random.uniform(0.6, 1.0),
                 color, random.uniform(2.5, 6.0)]
            )

    def update(self, dt):
        alive = []
        for p in self.items:
            p[4] -= dt
            if p[4] <= 0:
                continue
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] += 520 * dt
            p[2] *= 0.965
            alive.append(p)
        self.items = alive

    def draw(self, dest):
        for x, y, _vx, _vy, life, life0, color, radius in self.items:
            t = life / life0
            theme.blit_glow(dest, color, (x, y), radius * (0.6 + t), t * 0.9)


class Shockwaves:
    """Expanding rings. Drawn directly - cheaper than compositing alpha."""

    __slots__ = ("items",)

    def __init__(self):
        self.items = []

    def add(self, pos, color, radius=110, life=0.42, width=3):
        self.items.append([pos[0], pos[1], color, radius, life, life, width])

    def update(self, dt):
        for item in self.items:
            item[4] -= dt
        self.items = [i for i in self.items if i[4] > 0]

    def draw(self, dest):
        for x, y, color, radius, life, life0, width in self.items:
            t = 1.0 - life / life0
            r = int(10 + theme.ease_out(t) * radius)
            fade = (1.0 - t) ** 1.6
            pygame.draw.circle(dest, theme.scale_color(color, fade), (int(x), int(y)), r,
                               max(1, int(width * fade) + 1))


class Bloom:
    """Threshold + blur + additive recombine, done entirely with smoothscale."""

    def __init__(self, size=theme.LOGICAL_SIZE, divisor=8, threshold=52, strength=0.85):
        self.small = (max(1, size[0] // divisor), max(1, size[1] // divisor))
        self.tiny = (max(1, self.small[0] // 2), max(1, self.small[1] // 2))
        self.size = size
        self.threshold = threshold
        self.strength = strength
        self._buf_small = pygame.Surface(self.small)
        self._buf_tiny = pygame.Surface(self.tiny)
        self._buf_full = pygame.Surface(size)

    def apply(self, canvas):
        pygame.transform.smoothscale(canvas, self.small, self._buf_small)
        t = self.threshold
        self._buf_small.fill((t, t, t), special_flags=pygame.BLEND_RGB_SUB)
        pygame.transform.smoothscale(self._buf_small, self.tiny, self._buf_tiny)
        pygame.transform.smoothscale(self._buf_tiny, self.size, self._buf_full)
        k = int(255 * self.strength)
        self._buf_full.fill((k, k, k), special_flags=pygame.BLEND_RGB_MULT)
        canvas.blit(self._buf_full, (0, 0), special_flags=pygame.BLEND_ADD)


class FloatingText:
    """Grade labels that rise and fade."""

    __slots__ = ("items",)

    def __init__(self):
        self.items = []

    def add(self, pos, surf, life=0.7, rise=42):
        self.items.append([pos[0], pos[1], surf, life, life, rise])

    def update(self, dt):
        for item in self.items:
            item[3] -= dt
        self.items = [i for i in self.items if i[3] > 0]

    def draw(self, dest):
        for x, y, surf, life, life0, rise in self.items:
            t = 1.0 - life / life0
            alpha = int(255 * min(1.0, (1.0 - t) * 2.2))
            surf.set_alpha(alpha)
            dest.blit(surf, (int(x - surf.get_width() / 2), int(y - theme.ease_out(t) * rise)))
            surf.set_alpha(255)
