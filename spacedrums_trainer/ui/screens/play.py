"""The highway. Reads hits from the hub, judges them against the run, draws.

Colour means limb: blue left hand, red right hand, amber either foot.
Cymbals are rings, drums are solid discs.
"""

from __future__ import annotations

import math
import time

import pygame

from ...rhythms import HAT_PEDAL, KICK
from ...session import COUNT_IN_BEATS, Run
from .. import fx, theme, widgets
from ..app import Screen
from ..theme import LANES

# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------
CENTER_X = 640
HIGHWAY_TOP = 92
HIT_Y = 476

LANE_W_MIN, LANE_W_MAX = 120, 180
HIGHWAY_MAX_W = 852
FRAME_MIN_W = 640
NOTE_R_MAX = 29.0

FOOT_RAIL_Y = 498
PAD_UPPER_Y = 544
PAD_LOWER_Y = 634
PAD_SINGLE_Y = 558
PAD_UPPER_R = 26
PAD_LOWER_R = 30

METER_Y = 690
METER_HALF = 150
METER_MS = 200.0

CYMBALS = {1, 5, 6}
FOOT_COLOR = theme.FOOT

GRADE_COLORS = {"PERFECT": (150, 235, 255), "GOOD": theme.GOOD,
                "OK": theme.WARN, "MISS": theme.BAD}

# Keyboard stand-in so the game is playable without the sticks plugged in.
KEY_DRUMS = {pygame.K_a: (1, 1), pygame.K_s: (6, 1), pygame.K_d: (3, 1),
             pygame.K_f: (2, 0), pygame.K_g: (4, 0), pygame.K_h: (7, 0),
             pygame.K_j: (5, 1)}


class PlayScreen(Screen):
    def __init__(self, app, rhythm, start_bpm, level_number=None, loops=16):
        super().__init__(app)
        self.rhythm = rhythm
        self.level_number = level_number
        self.run = Run(rhythm, start_bpm, loops)
        self.lookahead = app.settings.get("lookahead_s", 2.6)
        self.metronome = app.settings.get("metronome", True)

        self.particles = fx.Particles()
        self.waves = fx.Shockwaves()
        self.pad_flash: dict[int, list] = {}
        self.ticks: list[list] = []
        self.grade_flash: list | None = None
        self.accuracy_shown = 100.0
        self.combo_pop = 0.0
        self.hat_open_until = -1.0
        self.finishing = 0.0

        voices = rhythm.voices()
        self.lanes = sorted({d for d in voices if d in LANES}, key=lambda d: LANES[d].yaw)
        self.uses_kick = KICK in voices
        self.uses_hh_pedal = HAT_PEDAL in voices

        count = max(1, len(self.lanes))
        self.lane_w = max(LANE_W_MIN, min(LANE_W_MAX, HIGHWAY_MAX_W / count))
        self.highway_w = self.lane_w * count
        self.x0 = CENTER_X - self.highway_w / 2
        self.frame_w = max(FRAME_MIN_W, self.highway_w)
        self.frame_x0 = CENTER_X - self.frame_w / 2

        if len({LANES[d].tier for d in self.lanes}) == 2:
            self.tier_y = {1: PAD_UPPER_Y, 0: PAD_LOWER_Y}
            self.tier_r = {1: PAD_UPPER_R, 0: PAD_LOWER_R}
        else:
            self.tier_y = {1: PAD_SINGLE_Y, 0: PAD_SINGLE_Y}
            self.tier_r = {1: 29, 0: 29}

        groups: dict[int, list] = {}
        for note in self.run.notes:
            groups.setdefault(int(round(note.t * 1000)), []).append(note)
        self.links = [g for g in groups.values()
                      if len([x for x in g if x.drum in LANES]) > 1]

        self.song_time = 0.0

    # ------------------------------------------------------------------
    def on_enter(self):
        if self.app.kit:
            self.app.kit.set_hat_closed(True)
        self._drain_input()
        self.run.start(self.app.settings.get("input_offset_ms", 0))
        self._schedule_metronome()

    def _schedule_metronome(self):
        scheduler = self.app.scheduler
        if not scheduler:
            return
        scheduler.clear()
        for when, accent in self.run.beat_lines:
            scheduler.at(self.run.started_at + when, self._click(accent))

    def _click(self, accent):
        def go():
            if self.metronome and self.app.kit:
                self.app.kit.click(accent)
        return go

    def _leave(self):
        if self.app.scheduler:
            self.app.scheduler.clear()

    # ------------------------------------------------------------------
    def lane_x(self, drum):
        return self.x0 + self.lanes.index(drum) * self.lane_w + self.lane_w / 2

    def pad_pos(self, drum):
        return self.lane_x(drum), self.tier_y[LANES[drum].tier]

    def foot_span(self, right_foot):
        if right_foot:
            return int(CENTER_X + 5), int(self.frame_x0 + self.frame_w) + 13
        return int(self.frame_x0) - 13, int(CENTER_X - 5)

    @staticmethod
    def limb_color(note):
        if note.drum not in LANES:
            return FOOT_COLOR
        return theme.STICK_COLORS.get(note.stick, theme.NEUTRAL)

    def flash_of(self, drum):
        entry = self.pad_flash.get(drum)
        return (max(0.0, entry[0]) / 0.34, entry[1]) if entry else (0.0, theme.NEUTRAL)

    def time_to_y(self, t):
        p = 1.0 - (t - self.song_time) / self.lookahead
        return HIGHWAY_TOP + p * (HIT_Y - HIGHWAY_TOP), p

    # ------------------------------------------------------------------
    def handle(self, event):
        if event.type != pygame.KEYDOWN and event.type != pygame.KEYUP:
            return
        hub = self.app.hub

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._leave()
                self.app.pop()
            elif event.key == pygame.K_m:
                self.metronome = not self.metronome
                self.app.toast(f"Metronome {'on' if self.metronome else 'off'}")
            elif event.key in KEY_DRUMS and hub:
                drum, stick = KEY_DRUMS[event.key]
                hub.feed_hit(drum, 5, stick)
            elif event.key == pygame.K_SPACE and hub:
                hub.feed_pedal(1, True)
            elif event.key in (pygame.K_LSHIFT, pygame.K_RSHIFT) and hub:
                hub.feed_pedal(0, False)
        elif event.key in (pygame.K_LSHIFT, pygame.K_RSHIFT) and hub:
            hub.feed_pedal(0, True)

    # ------------------------------------------------------------------
    def update(self, dt, t):
        self.song_time = self.run.now()
        self._drain_input()

        for note in self.run.expire(self.song_time):
            self._feedback(note)

        self.particles.update(dt)
        self.waves.update(dt)
        if self.grade_flash:
            self.grade_flash[2] -= dt
            if self.grade_flash[2] <= 0:
                self.grade_flash = None
        for key in list(self.pad_flash):
            self.pad_flash[key][0] -= dt
            if self.pad_flash[key][0] <= 0:
                del self.pad_flash[key]
        for tick in self.ticks:
            tick[1] -= dt
        self.ticks = [x for x in self.ticks if x[1] > 0]

        self.accuracy_shown = theme.approach(self.accuracy_shown, self.run.accuracy, dt, 8.0)
        self.combo_pop = max(0.0, self.combo_pop - dt * 3.4)

        if self.run.finished(self.song_time):
            self.finishing += dt
            if self.finishing > 0.5:
                self._finish()

    def _drain_input(self):
        hub = self.app.hub
        if hub is None:
            return
        while True:
            try:
                event = hub.events.get_nowait()
            except Exception:
                return
            kind, stamp = event[0], event[1]
            run_t = stamp - self.run.started_at
            if kind == "hit":
                note = self.run.hit(run_t, event[2])
                if note is not None:
                    self._feedback(note)
            elif kind == "pedal":
                pressed = event[4]
                if not pressed:
                    self.hat_open_until = self.song_time + 0.6
                self.pad_flash[HAT_PEDAL] = [0.34, FOOT_COLOR]

    def _finish(self):
        self._leave()
        from .results import ResultsScreen

        self.app.replace(ResultsScreen(self.app, self.run, self.level_number))

    # ------------------------------------------------------------------
    def _feedback(self, note):
        color = GRADE_COLORS[note.grade]
        limb = self.limb_color(note)
        self.grade_flash = [note.grade, color, 0.5]

        if note.grade == "MISS":
            return

        if note.drum in LANES:
            pos = self.pad_pos(note.drum)
            self.waves.add(pos, limb, radius=50, life=0.36)
            self.particles.burst(pos, limb, count=14, speed=280)
        else:
            xa, xb = self.foot_span(note.drum == KICK)
            pos = ((xa + xb) / 2, FOOT_RAIL_Y)
            self.waves.add(pos, limb, radius=78, life=0.40, width=3)
            self.particles.burst(pos, limb, count=14, speed=260, spread=math.pi * 1.4)
            if note.drum == KICK:
                self.app.background.kick(0.8)

        self.pad_flash[note.drum] = [0.34, limb]
        self.combo_pop = 1.0
        self.ticks.append([note.delta * 1000.0, 1.6, color])

    # ==================================================================
    # Drawing
    # ==================================================================
    def draw(self, dest):
        f, ov = self.app.fonts, self.app.overlay
        self.beat = self.run.beat_at(self.song_time)
        self._draw_highway(dest)
        self._draw_beat_grid(dest, ov, f)
        self._draw_lane_beams(dest)
        self._draw_notes(dest, ov, f)
        self._draw_hit_line(dest)
        self._draw_pads(dest, ov, f)
        self.waves.draw(dest)
        self.particles.draw(dest)
        self._draw_hud(dest, ov, f)
        self._draw_meter(dest, ov, f)
        self._draw_count_in(dest, ov, f)

    def _draw_highway(self, dest):
        h = HIT_Y - HIGHWAY_TOP
        frame = pygame.Surface((int(self.frame_w), h), pygame.SRCALPHA)
        frame.fill((255, 255, 255, 5))
        lane_ox = int(self.x0 - self.frame_x0)
        pygame.draw.rect(frame, (255, 255, 255, 6), (lane_ox, 0, int(self.highway_w), h))
        for i in range(1, len(self.lanes)):
            x = lane_ox + int(i * self.lane_w)
            pygame.draw.line(frame, (255, 255, 255, 20), (x, 0), (x, h))
        dest.blit(frame, (int(self.frame_x0), HIGHWAY_TOP))

        for side, x in ((-1, int(self.frame_x0)), (1, int(self.frame_x0 + self.frame_w))):
            wall = theme.column((84, 108, 158), 90, h, 34)
            dest.blit(wall, (x if side > 0 else x - 90, HIGHWAY_TOP))
            pygame.draw.line(dest, (150, 170, 210), (x, HIGHWAY_TOP), (x, HIT_Y))

    def _draw_beat_grid(self, dest, ov, f):
        left, right = int(self.frame_x0), int(self.frame_x0 + self.frame_w)
        bar = 0
        for when, is_bar in self.run.beat_lines:
            if is_bar and when >= self.run.music_start:
                bar += 1
            if when < self.song_time - 0.2 or when > self.song_time + self.lookahead:
                continue
            y, p = self.time_to_y(when)
            if not (HIGHWAY_TOP - 2 <= y <= HIT_Y):
                continue
            fade = min(1.0, max(0.0, p * 3.0))
            shade = int((84 if is_bar else 24) * fade)
            pygame.draw.line(dest, (shade + 14, shade + 17, shade + 26),
                             (left, int(y)), (right, int(y)))
            if is_bar and bar:
                num = f.render("mono", 12, str(bar), theme.TEXT_FAINT)
                num.set_alpha(int(150 * fade))
                ov.blit(num, (left - 28, int(y) - 7))
                num.set_alpha(255)

    def _draw_lane_beams(self, dest):
        h = HIT_Y - HIGHWAY_TOP
        horizon = self.beat * 2.0
        for drum in self.lanes:
            upcoming = None
            for note in self.run.notes:
                if note.t < self.song_time or note.drum != drum:
                    continue
                upcoming = note
                break
            if upcoming is None or upcoming.t - self.song_time > horizon:
                continue
            intensity = (1.0 - (upcoming.t - self.song_time) / horizon) ** 2
            beam = theme.column(self.limb_color(upcoming), int(self.lane_w) - 4, h, 44)
            beam.set_alpha(int(125 * intensity))
            dest.blit(beam, (int(self.lane_x(drum) - self.lane_w / 2 + 2), HIGHWAY_TOP))
            beam.set_alpha(255)

    # ------------------------------------------------------------------
    def _draw_notes(self, dest, ov, f):
        window_end = self.song_time + self.lookahead
        for note in self.run.notes:
            if note.t > window_end + 1.0:
                break
            if note.drum == HAT_PEDAL:
                self._draw_open_window(dest, ov, f, note)

        for group in self.links:
            if group[0].t < self.song_time - 0.1 or group[0].t > window_end:
                continue
            members = [x for x in group if x.drum in LANES and x.state == 0]
            if len(members) < 2:
                continue
            y, p = self.time_to_y(group[0].t)
            xs = [self.lane_x(x.drum) for x in members]
            fade = min(1.0, max(0.0, p / 0.12))
            pygame.draw.line(dest, theme.scale_color((196, 208, 236), fade * (0.35 + 0.65 * p)),
                             (int(min(xs)), int(y)), (int(max(xs)), int(y)), 3)

        for note in self.run.notes:
            if note.t > window_end:
                break
            y, p = self.time_to_y(note.t)
            if p < 0.03 or p > 1.2 or note.state == 1 or note.drum == HAT_PEDAL:
                continue
            if note.drum in LANES:
                self._draw_disc(dest, ov, f, note, y, p)
            else:
                self._draw_pedal_bar(dest, ov, f, note, y, p)

    def _draw_open_window(self, dest, ov, f, note):
        y_bot, p_bot = self.time_to_y(note.t)
        y_top, p_top = self.time_to_y(note.t + note.dur)
        if p_bot > 1.3 or p_top < 0.0:
            return
        y_bot, y_top = min(y_bot, HIT_Y), max(y_top, HIGHWAY_TOP)
        if y_bot - y_top < 2:
            return

        xa, xb = self.foot_span(False)
        fade = min(1.0, max(0.0, p_top / 0.10)) * (0.55 + 0.45 * min(1.0, p_bot))

        band = pygame.Surface((xb - xa, int(y_bot - y_top)), pygame.SRCALPHA)
        band.fill((*FOOT_COLOR, int(30 * fade)))
        dest.blit(band, (xa, int(y_top)))

        # Lower edge is where the foot lifts, upper edge where it closes again.
        for sx in range(xa, xb, 24):
            end = min(sx + 13, xb)
            pygame.draw.line(dest, theme.scale_color(FOOT_COLOR, fade), (sx, y_bot), (end, y_bot), 5)
            pygame.draw.line(dest, theme.scale_color(FOOT_COLOR, fade * 0.45),
                             (sx, y_top), (end, y_top), 2)

        label = f.render("ui", 11, "LIFT", FOOT_COLOR, tracking=2)
        label.set_alpha(int(230 * fade))
        ov.blit(label, (xa - 14 - label.get_width(), int(y_bot - label.get_height() / 2)))
        label.set_alpha(255)

    def _draw_disc(self, dest, ov, f, note, y, p):
        x = self.lane_x(note.drum)
        fade = 0.32 + 0.68 * min(1.0, p / 0.10)
        if note.state == 2:
            fade *= max(0.0, 1.0 - (p - 1.0) * 6.0)
        scale = 0.64 + 0.36 * min(1.0, p)
        r = min(self.lane_w * 0.30, NOTE_R_MAX) * scale
        fade *= 0.66 + 0.34 * min(1.0, p)
        color = self.limb_color(note)
        if note.state == 2:
            color = theme.lerp(color, (90, 90, 100), 0.75)

        for i in range(1, 4):
            theme.blit_glow(dest, color, (x, y - i * 13 * scale), r * 2.0 * (1 - 0.16 * i),
                            fade * 0.15 * (1 - 0.25 * i) * p)
        theme.blit_glow(dest, color, (x, y), r * 2.7, fade * (0.14 + 0.66 * p ** 3))

        if note.drum in CYMBALS:
            pygame.draw.circle(dest, theme.scale_color(color, fade), (int(x), int(y)), int(r),
                               max(3, int(r * 0.30)))
            pygame.draw.circle(dest, theme.scale_color(color, 0.55 * fade), (int(x), int(y)),
                               max(2, int(r * 0.18)))
        else:
            pygame.draw.circle(dest, theme.scale_color(color, 0.42 * fade), (int(x), int(y)), int(r))
            pygame.draw.circle(dest, theme.scale_color(color, 0.72 * fade), (int(x), int(y)),
                               int(r * 0.62))
            pygame.draw.circle(dest, theme.scale_color(color, fade), (int(x), int(y)), int(r),
                               max(2, int(r * 0.20)))

        if note.state == 0 and 0.12 < p < 0.97:
            ring_r = r * (1.0 + 1.45 * (1.0 - p))
            pygame.draw.circle(dest, theme.scale_color(color, fade * 0.30 * p),
                               (int(x), int(y)), int(ring_r), 1)

        if note.open:
            pygame.draw.circle(dest, theme.scale_color(FOOT_COLOR, fade * 0.85),
                               (int(x), int(y)), int(r * 1.34), 2)

    def _draw_pedal_bar(self, dest, ov, f, note, y, p):
        fade = 0.32 + 0.68 * min(1.0, p / 0.10)
        if note.state == 2:
            fade *= max(0.0, 1.0 - (p - 1.0) * 6.0)
        color = FOOT_COLOR if note.state != 2 else theme.lerp(FOOT_COLOR, (90, 90, 100), 0.75)

        xa, xb = self.foot_span(True)
        w, h = xb - xa, int(11 * (0.7 + 0.3 * p))
        theme.blit_glow(dest, color, ((xa + xb) / 2, y), w * 0.44, fade * (0.07 + 0.22 * p ** 3))
        bar = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(bar, (*color, int((70 + 145 * min(1.0, p)) * fade)),
                         (0, 0, w, h), border_radius=h // 2)
        dest.blit(bar, (xa, int(y - h / 2)))

        tip = xb + 15
        pygame.draw.polygon(dest, theme.scale_color(color, fade * 0.75),
                            [(tip - 8, y - 9), (tip + 6, y), (tip - 8, y + 9)])
        label = f.render("ui", 11, "KICK", color, tracking=2)
        label.set_alpha(int(220 * fade * min(1.0, 0.4 + p)))
        ov.blit(label, (int(tip + 14), int(y - label.get_height() / 2)))
        label.set_alpha(255)

    # ------------------------------------------------------------------
    def _draw_hit_line(self, dest):
        left, right = int(self.frame_x0) - 16, int(self.frame_x0 + self.frame_w) + 16
        pulse = (1.0 - (self.song_time / self.beat) % 1.0) ** 3
        theme.blit_glow(dest, (150, 190, 255), (CENTER_X, HIT_Y), self.frame_w * 0.42,
                        0.16 + 0.18 * pulse)
        widgets.capsule(dest, (left, HIT_Y - 13, right - left, 26), (140, 180, 255),
                        int(24 + 16 * pulse))
        pygame.draw.line(dest, theme.lerp((198, 220, 255), (255, 255, 255), pulse),
                         (left, HIT_Y), (right, HIT_Y), 3)
        for x in (left, right):
            pygame.draw.circle(dest, (238, 246, 255), (x, HIT_Y), 5)

    def _draw_pads(self, dest, ov, f):
        for drum in self.lanes:
            lane = LANES[drum]
            x, y = self.pad_pos(drum)
            r = self.tier_r[lane.tier]
            flash, hot = self.flash_of(drum)

            pygame.draw.line(dest, theme.scale_color(theme.NEUTRAL, 0.22),
                             (int(x), HIT_Y + 2), (int(x), int(y) - r))
            if flash > 0:
                col = theme.column(hot, int(self.lane_w) - 6, HIT_Y - HIGHWAY_TOP, 80)
                col.set_alpha(int(190 * flash))
                dest.blit(col, (int(x - self.lane_w / 2 + 3), HIGHWAY_TOP))
                col.set_alpha(255)
                theme.blit_glow(dest, hot, (x, y), r * 2.2, 0.15 + 0.35 * flash)

            bump = int(flash * 3)
            ring = theme.lerp(theme.NEUTRAL, hot, flash)
            width = 3 if drum in CYMBALS else 2
            pygame.draw.circle(dest, theme.scale_color(ring, 0.12 + 0.38 * flash),
                               (int(x), int(y)), r + bump)
            pygame.draw.circle(dest, theme.scale_color(ring, 0.6 + 0.4 * flash),
                               (int(x), int(y)), r + bump, width)
            short = f.render("ui", 12, lane.short,
                             theme.lerp(theme.TEXT_SOFT, (255, 255, 255), flash), tracking=1)
            ov.blit(short, (int(x - short.get_width() / 2), int(y - short.get_height() / 2)))

        if self.uses_kick or self.uses_hh_pedal:
            self._draw_foot_rail(dest, ov, f)

    def _draw_foot_rail(self, dest, ov, f):
        hat_open = self.song_time < self.hat_open_until
        halves = ((HAT_PEDAL, False, "OPEN" if hat_open else "HAT DOWN", self.uses_hh_pedal),
                  (KICK, True, "KICK", self.uses_kick))
        for drum, right_foot, text, in_use in halves:
            xa, xb = self.foot_span(right_foot)
            flash, hot = self.flash_of(drum)
            if drum == HAT_PEDAL and hat_open:
                flash, hot = 1.0, FOOT_COLOR
            color = theme.lerp(theme.NEUTRAL, hot, flash)
            base = min(255, int((34 if in_use else 14) + 180 * flash))

            if flash > 0:
                theme.blit_glow(dest, hot, ((xa + xb) / 2, FOOT_RAIL_Y), (xb - xa) * 0.34,
                                0.12 + 0.30 * flash)
            rail = pygame.Surface((xb - xa, 12), pygame.SRCALPHA)
            pygame.draw.rect(rail, (*color, base), (0, 0, xb - xa, 12), border_radius=6)
            pygame.draw.rect(rail, (*color, min(255, base + 46)), (0, 0, xb - xa, 12),
                             width=1, border_radius=6)
            dest.blit(rail, (xa, FOOT_RAIL_Y - 6))

            tint = theme.TEXT_FAINT if in_use else (58, 64, 78)
            label = f.render("ui", 11, text, theme.lerp(tint, (255, 255, 255), flash), tracking=2)
            ov.blit(label, (xb + 14 if right_foot else xa - 14 - label.get_width(),
                            FOOT_RAIL_Y - 8))

    # ------------------------------------------------------------------
    def _draw_hud(self, dest, ov, f):
        run = self.run
        ov.blit(f.render("display", 27, self.rhythm.name, theme.TEXT, bold=True), (60, 26))
        if self.level_number:
            ov.blit(f.render("ui", 11, f"LEVEL {self.level_number}", theme.ACCENT, tracking=3),
                    (61, 60))

        bpm = int(round(run.bpm_at(self.song_time)))
        ov.blit(f.render("mono", 13, f"{bpm} BPM", theme.TEXT_SOFT), (61, 80))

        if self.grade_flash:
            name, color, life = self.grade_flash
            k = min(1.0, life / 0.5)
            ov.blit(f.render("display", 28, name, theme.scale_color(color, 0.35 + 0.65 * k),
                             bold=True, tracking=2), (60, 116 - int((1 - k) * 8)))

        # Tempo ramp: how far from the starting speed to the target.
        ramp = pygame.Rect(CENTER_X - 130, 52, 260, 8)
        span = max(1, run.target_bpm - run.start_bpm)
        widgets.progress_bar(dest, ramp, (bpm - run.start_bpm) / span, theme.FOOT)
        label = f.render("ui", 11, f"{run.start_bpm}  SPEEDING UP TO  {run.target_bpm}",
                         theme.TEXT_FAINT, tracking=2)
        ov.blit(label, (CENTER_X - label.get_width() // 2, 26))

        loop = min(run.loops, run.loop_index(self.song_time) + 1)
        progress = pygame.Rect(CENTER_X - 130, 70, 260, 4)
        widgets.progress_bar(dest, progress, run.progress(self.song_time), theme.ACCENT, glow=False)
        sub = f.render("mono", 11, f"loop {loop} / {run.loops}", theme.TEXT_FAINT)
        ov.blit(sub, (CENTER_X - sub.get_width() // 2, 78))

        acc = f.render("display", 36, f"{self.accuracy_shown:.0f}%", theme.TEXT, bold=True)
        ov.blit(acc, (1220 - acc.get_width(), 22))
        pop = theme.ease_out(self.combo_pop)
        combo_color = theme.lerp(theme.TEXT_SOFT, theme.ACCENT, min(1.0, run.combo / 40.0))
        combo = f.render("display", int(18 + pop * 4), f"x{run.combo}", combo_color, bold=True)
        ov.blit(combo, (1220 - combo.get_width(), 66))

        hint = "A S D F G H J drums    SPACE kick    SHIFT hat pedal    M metronome    ESC quit"
        ov.blit(f.render("ui", 13, hint, theme.TEXT_SOFT), (60, 700))

    def _draw_meter(self, dest, ov, f):
        y = METER_Y
        pygame.draw.line(dest, (46, 54, 70), (CENTER_X - METER_HALF, y), (CENTER_X + METER_HALF, y), 2)
        pygame.draw.line(dest, (120, 140, 172), (CENTER_X, y - 7), (CENTER_X, y + 7), 2)
        early = f.render("ui", 10, "EARLY", theme.TEXT_FAINT, tracking=2)
        ov.blit(early, (CENTER_X - METER_HALF - 14 - early.get_width(), y - early.get_height() // 2))
        ov.blit(f.render("ui", 10, "LATE", theme.TEXT_FAINT, tracking=2),
                (CENTER_X + METER_HALF + 14, y - early.get_height() // 2))
        for ms, life, color in self.ticks:
            x = CENTER_X + max(-METER_HALF, min(METER_HALF, ms / METER_MS * METER_HALF))
            pygame.draw.line(dest, theme.scale_color(color, life / 1.6),
                             (int(x), y - 9), (int(x), y + 9), 2)

    def _draw_count_in(self, dest, ov, f):
        remaining = self.run.music_start - self.song_time
        if remaining <= 0:
            return
        beat = 60.0 / self.run.start_bpm
        count = min(COUNT_IN_BEATS, int(remaining / beat) + 1)
        phase = 1.0 - (remaining / beat) % 1.0
        scale = 1.0 + 0.25 * (1.0 - phase) ** 2

        theme.blit_glow(dest, theme.ACCENT, (CENTER_X, 300), 300, 0.30)
        num = f.render("display", int(120 * scale), str(count), theme.TEXT, bold=True)
        ov.blit(num, (CENTER_X - num.get_width() // 2, 300 - num.get_height() // 2))
        ready = f.render("ui", 14, "GET READY", theme.TEXT_SOFT, tracking=4)
        ov.blit(ready, (CENTER_X - ready.get_width() // 2, 392))
