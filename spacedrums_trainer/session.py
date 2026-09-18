"""A practice run: the tempo ramp, the note timeline, judging and scoring.

Pure logic - no pygame, no rendering. The tempo climbs one step per loop from
the starting speed to the rhythm's target, so a beginner always begins slow
and arrives at full speed without ever noticing a jump.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .rhythms import HAT_PEDAL, Rhythm

DEFAULT_LOOPS = 16
COUNT_IN_BEATS = 4

# Deliberately generous: air drumming has no rebound surface and this is a
# beginner tool. Windows also shrink with tempo so they never overlap notes.
MAX_WINDOW = 0.24
WINDOW_BEAT_FRACTION = 0.45

PERFECT_FRACTION = 0.35
GOOD_FRACTION = 0.62

POINTS = {"PERFECT": 100, "GOOD": 75, "OK": 45, "MISS": 0}


@dataclass
class PlayNote:
    t: float
    drum: int
    stick: str | None
    dur: float
    window: float
    loop: int
    open: bool = False
    state: int = 0        # 0 pending, 1 hit, 2 missed
    grade: str = ""
    delta: float = 0.0


class Run:
    """One attempt at one rhythm."""

    def __init__(self, rhythm: Rhythm, start_bpm: int, loops=DEFAULT_LOOPS, metronome=True):
        self.rhythm = rhythm
        self.target_bpm = rhythm.target_bpm
        self.start_bpm = max(30, min(int(start_bpm), self.target_bpm))
        self.loops = max(2, loops)
        self.metronome = metronome

        self.notes: list[PlayNote] = []
        self.beat_lines: list[tuple[float, bool]] = []   # (time, is_bar_start)
        self.segments: list[tuple[float, float, float]] = []  # (t0, beat_dur, bpm)

        self._build()

        self.started_at = 0.0
        self.offset = 0.0
        self.points = 0
        self.max_points = sum(POINTS["PERFECT"] for nt in self.notes if nt.drum != HAT_PEDAL)
        self.judged = 0
        self.combo = 0
        self.best_combo = 0
        self.counts = {"PERFECT": 0, "GOOD": 0, "OK": 0, "MISS": 0}
        self.ghosts = 0
        self.deltas: list[float] = []
        self._cursor = 0

    # ------------------------------------------------------------------
    def _build(self):
        beat_start = 60.0 / self.start_bpm
        t = 0.0

        for i in range(COUNT_IN_BEATS):
            self.beat_lines.append((t, i == 0))
            t += beat_start
        self.segments.append((0.0, beat_start, self.start_bpm))
        self.music_start = t

        span = self.target_bpm - self.start_bpm
        for loop in range(self.loops):
            frac = loop / max(1, self.loops - 1)
            bpm = self.start_bpm + span * frac
            beat = 60.0 / bpm
            self.segments.append((t, beat, bpm))

            for beat_index in range(self.rhythm.beats):
                self.beat_lines.append((t + beat_index * beat, beat_index % 4 == 0))

            window = min(MAX_WINDOW, beat * WINDOW_BEAT_FRACTION)
            for b, drum, stick, dur in self.rhythm.notes:
                self.notes.append(PlayNote(t + b * beat, drum, stick, dur * beat, window, loop))

            t += self.rhythm.beats * beat

        self.end_time = t
        self.notes.sort(key=lambda nt: nt.t)

        holds = [(nt.t, nt.t + nt.dur) for nt in self.notes if nt.drum == HAT_PEDAL]
        for nt in self.notes:
            if nt.drum == 6:
                nt.open = any(a <= nt.t <= b for a, b in holds)

    # ------------------------------------------------------------------
    def start(self, offset_ms=0):
        self.started_at = time.perf_counter()
        self.offset = offset_ms / 1000.0

    def now(self):
        return time.perf_counter() - self.started_at

    def finished(self, t):
        return t >= self.end_time + 0.4

    def segment_at(self, t):
        seg = self.segments[0]
        for candidate in self.segments:
            if candidate[0] <= t:
                seg = candidate
            else:
                break
        return seg

    def bpm_at(self, t):
        return self.segment_at(t)[2]

    def beat_at(self, t):
        return self.segment_at(t)[1]

    def progress(self, t):
        span = self.end_time - self.music_start
        return max(0.0, min(1.0, (t - self.music_start) / span)) if span > 0 else 0.0

    def loop_index(self, t):
        if t < self.music_start:
            return 0
        for i in range(len(self.segments) - 1, 0, -1):
            if self.segments[i][0] <= t:
                return i - 1
        return 0

    # ------------------------------------------------------------------
    def expire(self, t):
        """Mark notes that sailed past their window. Returns the ones just missed."""
        missed = []
        for nt in self.notes:
            if nt.t > t:
                break
            if nt.state == 0 and nt.drum != HAT_PEDAL and t > nt.t + nt.window:
                nt.state = 2
                nt.grade = "MISS"
                self._score(nt)
                missed.append(nt)
        return missed

    def hit(self, t, drum):
        """Judge an incoming strike. Returns the note it matched, or None."""
        t -= self.offset
        best, best_delta = None, None
        for nt in self.notes:
            if nt.t - 0.5 > t:
                break
            if nt.state != 0 or nt.drum != drum:
                continue
            delta = t - nt.t
            if abs(delta) <= nt.window and (best_delta is None or abs(delta) < abs(best_delta)):
                best, best_delta = nt, delta

        if best is None:
            self.ghosts += 1
            return None

        best.state = 1
        best.delta = best_delta
        ratio = abs(best_delta) / best.window
        best.grade = ("PERFECT" if ratio <= PERFECT_FRACTION
                      else "GOOD" if ratio <= GOOD_FRACTION else "OK")
        self.deltas.append(best_delta)
        self._score(best)
        return best

    def _score(self, note):
        self.judged += 1
        self.counts[note.grade] += 1
        self.points += POINTS[note.grade]
        if note.grade == "MISS":
            self.combo = 0
        else:
            self.combo += 1
            self.best_combo = max(self.best_combo, self.combo)

    # ------------------------------------------------------------------
    @property
    def accuracy(self):
        return 100.0 * self.points / self.max_points if self.max_points else 100.0

    @property
    def hits(self):
        return self.counts["PERFECT"] + self.counts["GOOD"] + self.counts["OK"]

    @property
    def mean_delta_ms(self):
        return 1000.0 * sum(self.deltas) / len(self.deltas) if self.deltas else 0.0

    @property
    def stars(self):
        acc = self.accuracy
        return 3 if acc >= 92 else 2 if acc >= 80 else 1 if acc >= 65 else 0

    @property
    def passed(self):
        return self.accuracy >= 65

    def xp(self):
        speed_bonus = 1.0 + 0.5 * (self.start_bpm / self.target_bpm)
        gained = self.points / 12.0 * speed_bonus
        if self.counts["MISS"] == 0 and self.judged:
            gained += 120
        if self.stars == 3:
            gained += 90
        return int(gained)


class Demo:
    """Loops a rhythm through the kit so the player can hear it before playing."""

    def __init__(self, kit, scheduler, rhythm: Rhythm, bpm: int):
        self.kit = kit
        self.scheduler = scheduler
        self.rhythm = rhythm
        self.beat = 60.0 / max(30, bpm)
        self.flash: dict[int, float] = {}
        self.beat_origin = 0.0
        self._running = False

    def start(self):
        self._running = True
        self.beat_origin = time.perf_counter()
        self._arm(self.beat_origin)

    def stop(self):
        self._running = False
        self.scheduler.clear()

    def _arm(self, t0):
        if not self._running:
            return
        for b, drum, stick, _dur in self.rhythm.notes:
            when = t0 + b * self.beat
            self.scheduler.at(when, self._fire(drum, stick))
        self.scheduler.at(t0 + self.rhythm.beats * self.beat,
                          lambda: self._arm(t0 + self.rhythm.beats * self.beat))

    def _fire(self, drum, stick):
        def go():
            if not self._running:
                return
            if drum == HAT_PEDAL:
                self.kit.set_hat_closed(False)
                self.scheduler.at(time.perf_counter() + 0.35,
                                  lambda: self.kit.set_hat_closed(True))
                return
            self.kit.play(drum, 5, 0 if stick == "L" else 1 if stick == "R" else None)
            self.flash[drum] = time.perf_counter()
        return go
