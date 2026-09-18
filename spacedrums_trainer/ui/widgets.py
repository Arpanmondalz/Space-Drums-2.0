"""Glass panels, buttons and small readouts.

Panel backgrounds are rasterised once per (size, radius) and reused, so a
screen full of cards costs a handful of blits.
"""

from __future__ import annotations

import pygame

from . import theme

_PANEL_CACHE: dict[tuple, pygame.Surface] = {}


def panel(size, radius=18, fill=theme.GLASS_FILL, edge=theme.GLASS_EDGE) -> pygame.Surface:
    key = (size, radius, fill, edge)
    surf = _PANEL_CACHE.get(key)
    if surf is None:
        surf = pygame.Surface(size, pygame.SRCALPHA)
        pygame.draw.rect(surf, fill, (0, 0, *size), border_radius=radius)
        pygame.draw.rect(surf, edge, (0, 0, *size), width=1, border_radius=radius)
        # A brighter top edge reads as a light source above the card.
        pygame.draw.line(surf, (255, 255, 255, edge[3] + 26), (radius, 1), (size[0] - radius, 1))
        _PANEL_CACHE[key] = surf
    return surf


def draw_panel(dest, rect, radius=18, fill=theme.GLASS_FILL, edge=theme.GLASS_EDGE):
    dest.blit(panel((rect[2], rect[3]), radius, fill, edge), (rect[0], rect[1]))


def capsule(dest, rect, color, alpha=255):
    surf = pygame.Surface((rect[2], rect[3]), pygame.SRCALPHA)
    pygame.draw.rect(surf, (*color, alpha), (0, 0, rect[2], rect[3]), border_radius=rect[3] // 2)
    dest.blit(surf, (rect[0], rect[1]))


def progress_bar(dest, rect, fraction, color, track=(255, 255, 255, 22), glow=True):
    x, y, w, h = rect
    capsule(dest, rect, track[:3], track[3])
    filled = max(0, min(w, int(w * fraction)))
    if filled > 2:
        capsule(dest, (x, y, filled, h), color)
        if glow:
            theme.blit_glow(dest, color, (x + filled, y + h / 2), h * 2.2, 0.5)


class BackButton:
    """Top-left return control. Paired with Esc, never the only way out."""

    def __init__(self, pos=(60, 26), size=(106, 38)):
        self.rect = pygame.Rect(pos[0], pos[1], size[0], size[1])
        self.hot = 0.0

    def update(self, dt, mouse_pos):
        self.hot = theme.approach(self.hot, 1.0 if self.rect.collidepoint(mouse_pos) else 0.0,
                                  dt, 16.0)

    def clicked(self, pos):
        return self.rect.collidepoint(pos)

    def draw(self, dest, ov, f):
        r = self.rect
        if self.hot > 0.02:
            theme.blit_glow(dest, theme.ACCENT, r.center, r.w, self.hot * 0.22)
        draw_panel(dest, r, r.h // 2, (255, 255, 255, int(9 + self.hot * 16)),
                   (*theme.ACCENT, int(40 + self.hot * 110)))
        color = theme.lerp(theme.TEXT_SOFT, (255, 255, 255), self.hot)
        ax = r.x + 26
        pygame.draw.lines(dest, color, False,
                          [(ax + 5, r.centery - 6), (ax - 3, r.centery), (ax + 5, r.centery + 6)], 2)
        label = f.render("ui", 14, "Back", color)
        ov.blit(label, (r.x + 44, r.centery - label.get_height() // 2))


def key_hints(dest, ov, f, pos, pairs, align="left"):
    """A legible hint bar: each key in its own capsule, then what it does."""
    items = []
    total = 0
    for key, label in pairs:
        key_surf = f.render("mono", 13, key, theme.TEXT)
        label_surf = f.render("ui", 14, label, theme.TEXT_SOFT)
        cap_w = key_surf.get_width() + 20
        items.append((key_surf, label_surf, cap_w))
        total += cap_w + 10 + label_surf.get_width() + 30
    total -= 30

    x = pos[0]
    if align == "center":
        x -= total // 2
    elif align == "right":
        x -= total

    y = pos[1]
    for key_surf, label_surf, cap_w in items:
        capsule(dest, (x, y, cap_w, 26), (255, 255, 255), 30)
        ov.blit(key_surf, (x + 10, y + 5))
        ov.blit(label_surf, (x + cap_w + 10, y + 4))
        x += cap_w + 10 + label_surf.get_width() + 30


def speed_ladder(dest, pos, filled, total=6, color=theme.ACCENT, pip=7, gap=16):
    x, y = pos
    for i in range(total):
        cx = x + i * (pip * 2 + gap)
        if i < filled:
            pygame.draw.circle(dest, color, (cx, y), pip)
            theme.blit_glow(dest, color, (cx, y), pip * 3.4, 0.42)
        else:
            pygame.draw.circle(dest, (62, 70, 90), (cx, y), pip, 2)
        if i < total - 1:
            seg = theme.lerp((48, 55, 72), color, 1.0 if i < filled - 1 else 0.0)
            pygame.draw.line(dest, seg, (cx + pip + 3, y), (cx + pip + gap - 3, y), 2)


def stars(dest, pos, earned, total=3, size=13, gap=7):
    x, y = pos
    for i in range(total):
        color = theme.WARN if i < earned else (58, 66, 84)
        _star(dest, (x + i * (size * 2 + gap), y), size, color)
        if i < earned:
            theme.blit_glow(dest, theme.WARN, (x + i * (size * 2 + gap), y), size * 2.0, 0.35)


def _star(dest, center, r, color):
    import math

    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        pts.append((center[0] + math.cos(ang) * rad, center[1] + math.sin(ang) * rad))
    pygame.draw.polygon(dest, color, pts)


class Button:
    """Card-style button with eased hover/press and keyboard focus."""

    def __init__(self, rect, title, subtitle="", accent=theme.ACCENT, icon=None, radius=20,
                 compact=False):
        self.rect = pygame.Rect(rect)
        self.title = title
        self.subtitle = subtitle
        self.accent = accent
        self.icon = icon
        self.radius = radius
        self.compact = compact
        self.hot = 0.0
        self.press = 0.0
        self.lift = 0
        self.focused = False

    def update(self, dt, mouse_pos, mouse_down):
        hovered = self.rect.collidepoint(mouse_pos)
        target = 1.0 if (hovered or self.focused) else 0.0
        self.hot = theme.approach(self.hot, target, dt, 16.0)
        self.press = theme.approach(self.press, 1.0 if (hovered and mouse_down) else 0.0, dt, 26.0)
        self.lift = int(self.hot * 6 - self.press * 4)
        return hovered

    def draw(self, dest, ov, f: theme.Fonts):
        r = self.rect.move(0, -self.lift)

        if self.hot > 0.01:
            theme.blit_glow(dest, self.accent, r.center, max(r.w, r.h) * 0.82, self.hot * 0.30)

        edge_alpha = int(30 + self.hot * 95)
        fill_alpha = int(11 + self.hot * 16)
        draw_panel(dest, r, self.radius, (255, 255, 255, fill_alpha),
                   (*self.accent, edge_alpha) if self.hot > 0.02 else theme.GLASS_EDGE)

        if self.compact:
            title = f.render("display", 20, self.title,
                             theme.lerp(theme.TEXT, (255, 255, 255), self.hot), bold=True)
            ov.blit(title, (r.centerx - title.get_width() // 2,
                            r.centery - title.get_height() // 2))
            return

        cx = r.x + 30
        icon_color = theme.lerp(theme.TEXT_SOFT, self.accent, self.hot)
        if self.icon:
            bx, by = r.x + 62, r.y + 62
            theme.blit_glow(dest, self.accent, (bx, by), 92, 0.10 + self.hot * 0.30)
            pygame.draw.circle(dest, (26, 31, 45), (bx, by), 33)
            pygame.draw.circle(dest, (*icon_color, 90), (bx, by), 33, 1)
            self.icon(dest, (bx, by), 17, icon_color)

        # Accent rail along the bottom edge grows on hover.
        rail_w = int((r.w - 60) * theme.ease_out(self.hot))
        if rail_w > 2:
            capsule(dest, (cx, r.bottom - 14, rail_w, 3), self.accent)

        title = f.render("display", 27, self.title, theme.lerp(theme.TEXT, (255, 255, 255), self.hot), bold=True)
        ov.blit(title, (cx, r.bottom - 74))
        if self.subtitle:
            ov.blit(f.render("ui", 14, self.subtitle, theme.TEXT_SOFT), (cx, r.bottom - 40))


# --------------------------------------------------------------------------
# Vector icons
# --------------------------------------------------------------------------
def icon_rhythm(dest, center, size, color):
    x, y = center
    for i, h in enumerate((0.45, 0.85, 0.6, 1.0, 0.35)):
        bx = x - size + i * (size * 0.5)
        bh = int(size * h)
        capsule(dest, (int(bx), int(y - bh / 2), 5, bh), color)


def icon_kit(dest, center, size, color):
    x, y = center
    pygame.draw.circle(dest, color, (int(x), int(y + size * 0.25)), int(size * 0.55), 2)
    pygame.draw.line(dest, color, (x - size, y - size * 0.45), (x + size * 0.1, y - size * 0.1), 2)
    pygame.draw.line(dest, color, (x + size, y - size * 0.45), (x - size * 0.1, y - size * 0.1), 2)


def icon_gear(dest, center, size, color):
    import math

    x, y = center
    pygame.draw.circle(dest, color, (int(x), int(y)), int(size * 0.44), 2)
    for i in range(8):
        a = i * math.pi / 4
        pygame.draw.line(
            dest, color,
            (x + math.cos(a) * size * 0.62, y + math.sin(a) * size * 0.62),
            (x + math.cos(a) * size * 0.95, y + math.sin(a) * size * 0.95), 2,
        )
