"""Palette, typography and the pre-rendered glow cache.

Everything expensive here is built once and reused; nothing in this module
should ever allocate a surface inside a frame loop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pygame

LOGICAL_SIZE = (1280, 720)

_HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(os.path.dirname(_HERE), "assets", "fonts")

# --------------------------------------------------------------------------
# Palette - "Aurora": near-black desaturated navy, cool cymbals, warm drums.
# --------------------------------------------------------------------------
INK = (6, 8, 14)
BG_TOP = (17, 20, 32)
BG_BOTTOM = (7, 9, 16)

TEXT = (237, 241, 249)
TEXT_SOFT = (152, 162, 182)
TEXT_FAINT = (88, 98, 118)

ACCENT = (124, 206, 255)
ACCENT_WARM = (255, 178, 96)
GOOD = (112, 228, 162)
WARN = (255, 201, 96)
BAD = (255, 118, 118)

GLASS_FILL = (255, 255, 255, 11)
GLASS_EDGE = (255, 255, 255, 30)

# Notes are coloured by limb, not by drum: blue is the left side of your body,
# red the right. Reading a colour is instant; reading an "L" is not.
STICK_LEFT = (82, 166, 255)
STICK_RIGHT = (255, 94, 94)
STICK_COLORS = {"L": STICK_LEFT, "R": STICK_RIGHT}
NEUTRAL = (126, 138, 164)

# Feet get their own amber so a pedal never reads as a hand.
FOOT = (255, 202, 84)

AURORA = (
    ((56, 140, 210), 860, 0.190, 0.031, 0.21),
    ((150, 78, 200), 780, 0.150, 0.023, 4.10),
    ((210, 110, 96), 720, 0.115, 0.017, 2.30),
)


@dataclass(frozen=True)
class Lane:
    """A drum that occupies a column on the highway."""

    drum_id: int
    name: str
    short: str
    color: tuple[int, int, int]
    tier: int  # 1 = upper arc (reach up), 0 = lower arc
    yaw: float  # degrees from the calibrated snare aim


# Ordered by real yaw angle so left-to-right on screen matches the air.
LANES: dict[int, Lane] = {
    1: Lane(1, "Crash", "CR", (118, 236, 232), 1, -77.0),
    6: Lane(6, "Hi-Hat", "HH", (126, 196, 255), 0, -60.0),
    3: Lane(3, "Tom 1", "T1", (255, 148, 116), 1, -22.0),
    2: Lane(2, "Snare", "SN", (255, 193, 92), 0, 0.0),
    4: Lane(4, "Tom 2", "T2", (255, 124, 168), 1, 22.0),
    7: Lane(7, "Floor", "FL", (198, 132, 255), 0, 60.0),
    5: Lane(5, "Ride", "RD", (142, 250, 204), 1, 77.0),
}

LANE_ORDER = sorted(LANES, key=lambda d: LANES[d].yaw)

# Pedals never take a column - they sweep the full width of the highway.
KICK_ID, HIHAT_PEDAL_ID = 8, 9
PEDALS: dict[int, Lane] = {
    KICK_ID: Lane(KICK_ID, "Kick", "KI", (146, 154, 255), 0, 0.0),
    HIHAT_PEDAL_ID: Lane(HIHAT_PEDAL_ID, "Hi-Hat Pedal", "HP", (110, 188, 220), 0, -60.0),
}

ALL_VOICES = {**LANES, **PEDALS}


def lerp(a, b, t):
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def scale_color(color, k):
    return (
        max(0, min(255, int(color[0] * k))),
        max(0, min(255, int(color[1] * k))),
        max(0, min(255, int(color[2] * k))),
    )


# --------------------------------------------------------------------------
# Easing
# --------------------------------------------------------------------------
def ease_out(t):
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return 1.0 - (1.0 - t) ** 3


def ease_in_out(t):
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def approach(current, target, dt, rate=14.0):
    """Frame-rate independent exponential smoothing."""
    k = 1.0 - pow(0.5, dt * rate / 4.0)
    return current + (target - current) * k


# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------
_DISPLAY_CANDIDATES = "bahnschrift,montserrat,poppins,futura,cantarell,notosans,segoeui,dejavusans,liberationsans"
_UI_CANDIDATES = "inter,segoeui,cantarell,notosans,roboto,dejavusans,liberationsans,arial"
_MONO_CANDIDATES = "jetbrainsmono,cascadiamono,consolas,dejavusansmono,liberationmono,couriernew"


class Fonts:
    """Bundled fonts if present in assets/fonts, else the best system match."""

    def __init__(self):
        self._paths = {
            "display": self._resolve("display.ttf", _DISPLAY_CANDIDATES),
            "ui": self._resolve("ui.ttf", _UI_CANDIDATES),
            "mono": self._resolve("mono.ttf", _MONO_CANDIDATES),
        }
        self._cache: dict[tuple, pygame.font.Font] = {}
        self._text_cache: dict[tuple, pygame.Surface] = {}

    @staticmethod
    def _resolve(filename, candidates):
        bundled = os.path.join(FONT_DIR, filename)
        if os.path.isfile(bundled):
            return bundled
        return pygame.font.match_font(candidates)

    def get(self, kind, size, bold=False):
        key = (kind, size, bold)
        font = self._cache.get(key)
        if font is None:
            path = self._paths.get(kind)
            font = pygame.font.Font(path, size) if path else pygame.font.SysFont(None, size)
            font.set_bold(bold)
            self._cache[key] = font
        return font

    def render(self, kind, size, text, color, bold=False, tracking=0):
        """Cached text rasterisation with optional letter-spacing."""
        key = (kind, size, bold, text, color, tracking)
        surf = self._text_cache.get(key)
        if surf is not None:
            return surf

        font = self.get(kind, size, bold)
        if tracking == 0:
            surf = font.render(text, True, color)
        else:
            glyphs = [font.render(ch, True, color) for ch in text]
            width = sum(g.get_width() for g in glyphs) + tracking * max(0, len(glyphs) - 1)
            surf = pygame.Surface((max(1, width), font.get_height()), pygame.SRCALPHA)
            x = 0
            for g in glyphs:
                surf.blit(g, (x, 0))
                x += g.get_width() + tracking

        if len(self._text_cache) > 4000:
            self._text_cache.clear()
        self._text_cache[key] = surf
        return surf


_fonts: Fonts | None = None


def fonts() -> Fonts:
    global _fonts
    if _fonts is None:
        _fonts = Fonts()
    return _fonts


# --------------------------------------------------------------------------
# Glow sprites
#
# Stored as plain RGB surfaces that fade to black so they can be blitted with
# BLEND_ADD. Quantising radius and intensity keeps the cache small enough that
# after a few seconds of play nothing new is ever generated.
# --------------------------------------------------------------------------
_RADIAL_CACHE: dict[int, pygame.Surface] = {}
_GLOW_CACHE: dict[tuple, pygame.Surface] = {}
_SIZE_BUCKETS = (24, 32, 48, 64, 96, 128, 192, 256, 384)
_INTENSITY_STEPS = 8


def _radial(size: int) -> pygame.Surface:
    surf = _RADIAL_CACHE.get(size)
    if surf is not None:
        return surf
    surf = pygame.Surface((size, size))
    surf.fill((0, 0, 0))
    c = size // 2
    for r in range(c, 0, -1):
        t = r / c
        v = int(255 * (1.0 - t) ** 2.1)
        pygame.draw.circle(surf, (v, v, v), (c, c), r)
    _RADIAL_CACHE[size] = surf
    return surf


def make_glow(color, size: int, intensity: float) -> pygame.Surface:
    """One-off glow sprite at an exact size - use for large static art."""
    surf = _radial(size).copy()
    surf.fill(scale_color(color, intensity), special_flags=pygame.BLEND_RGB_MULT)
    return surf


def glow(color, radius: float, intensity: float = 1.0) -> pygame.Surface:
    target = max(8, int(radius * 2))
    size = next((s for s in _SIZE_BUCKETS if s >= target), _SIZE_BUCKETS[-1])
    step = max(1, min(_INTENSITY_STEPS, int(round(intensity * _INTENSITY_STEPS))))
    key = (color, size, step)
    surf = _GLOW_CACHE.get(key)
    if surf is None:
        surf = make_glow(color, size, step / _INTENSITY_STEPS)
        _GLOW_CACHE[key] = surf
    return surf


def blit_glow(dest: pygame.Surface, color, center, radius: float, intensity: float = 1.0):
    if intensity <= 0.02:
        return
    sprite = glow(color, radius, intensity)
    half = sprite.get_width() // 2
    dest.blit(sprite, (int(center[0]) - half, int(center[1]) - half), special_flags=pygame.BLEND_ADD)


def vertical_gradient(size, top, bottom) -> pygame.Surface:
    w, h = size
    strip = pygame.Surface((1, h))
    for y in range(h):
        strip.set_at((0, y), lerp(top, bottom, y / max(1, h - 1)))
    return pygame.transform.smoothscale(strip, (w, h))


_COLUMN_CACHE: dict[tuple, pygame.Surface] = {}


def column(color, width: int, height: int, peak_alpha=90) -> pygame.Surface:
    """Upward-fading column of light. Alpha-modulated with set_alpha by callers."""
    key = (color, width, height, peak_alpha)
    surf = _COLUMN_CACHE.get(key)
    if surf is None:
        strip = pygame.Surface((1, height), pygame.SRCALPHA)
        for y in range(height):
            t = y / max(1, height - 1)
            strip.set_at((0, y), (*color, int(peak_alpha * t * t)))
        surf = pygame.transform.smoothscale(strip, (width, height))
        _COLUMN_CACHE[key] = surf
    return surf

