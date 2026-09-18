"""The rhythm library.

Notes are stored in beats, never seconds, so the same data drives listening,
the tempo ramp and the highway at any speed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CRASH, SNARE, TOM1, TOM2, RIDE, HIHAT, FLOOR, KICK, HAT_PEDAL = range(1, 10)


@dataclass(frozen=True)
class Rhythm:
    id: str
    name: str
    blurb: str
    beats: int
    target_bpm: int
    notes: tuple = field(default_factory=tuple)

    @property
    def bars(self):
        return self.beats // 4

    def voices(self):
        return {n[1] for n in self.notes}


def n(beat, drum, stick=None, dur=0.0):
    return (round(beat, 4), drum, stick, dur)


def run(start, end, step, drum, stick=None):
    out, b = [], start
    while b < end - 1e-6:
        out.append(n(b, drum, stick))
        b += step
    return out


def eighths(start, end, drum, stick=None):
    return run(start, end, 0.5, drum, stick)


def quarters(start, end, drum, stick=None):
    return run(start, end, 1.0, drum, stick)


def open_hat(start, beats=0.45):
    """Left foot lifts at `start` and closes again `beats` later."""
    return n(start, HAT_PEDAL, None, beats)


def _backbeat(offset=0.0, stick="L"):
    return [n(offset + 1, SNARE, stick), n(offset + 3, SNARE, stick)]


def _rock(offset=0.0):
    return (eighths(offset, offset + 4, HIHAT, "R")
            + [n(offset, KICK), n(offset + 2, KICK)]
            + _backbeat(offset))


# --------------------------------------------------------------------------
# Learn to Play - an ordered curriculum, one rhythm per level.
# The steps are deliberately small: each level adds one idea, never two.
# --------------------------------------------------------------------------
LEVELS: list[Rhythm] = [
    Rhythm("lv01", "First Beats", "Two snare hits a bar, on 1 and 3. Nothing else.",
           4, 80, tuple([n(0, SNARE, "R"), n(2, SNARE, "R")])),

    Rhythm("lv02", "Quarter Notes", "Now all four beats. Count 1 2 3 4 out loud.",
           4, 80, tuple(quarters(0, 4, SNARE, "R"))),

    Rhythm("lv03", "Bass Drum", "Same two beats, this time with your right foot.",
           4, 80, tuple([n(0, KICK), n(2, KICK)])),

    Rhythm("lv04", "Bass Pulse", "Right foot on every beat.",
           4, 85, tuple(quarters(0, 4, KICK))),

    Rhythm("lv05", "Kick & Snare", "Foot on 1 and 3, hand on 2 and 4. Your first groove.",
           4, 85, tuple([n(0, KICK), n(2, KICK)] + _backbeat())),

    Rhythm("lv06", "Hi-Hat Pulse", "Right hand keeping quarter notes on the hi-hat.",
           4, 85, tuple(quarters(0, 4, HIHAT, "R"))),

    Rhythm("lv07", "Hat & Snare", "Hi-hat pulse with the backbeat underneath.",
           4, 90, tuple(quarters(0, 4, HIHAT, "R") + _backbeat())),

    Rhythm("lv08", "Three Limbs", "Hat, snare and kick together for the first time.",
           4, 90, tuple(quarters(0, 4, HIHAT, "R") + [n(0, KICK), n(2, KICK)] + _backbeat())),

    Rhythm("lv09", "Eighth Hats", "Eight even hi-hat notes. Keep the wrist loose.",
           4, 90, tuple(eighths(0, 4, HIHAT, "R"))),

    Rhythm("lv10", "Rock Beat", "Eighth hats over the groove. The one everybody learns.",
           4, 95, tuple(_rock())),

    Rhythm("lv11", "Rock Variation", "The second kick slides to the and of 2.",
           4, 95, tuple(eighths(0, 4, HIHAT, "R") + [n(0, KICK), n(1.5, KICK)] + _backbeat())),

    Rhythm("lv12", "Double Kick", "Two kicks in a row before the backbeat.",
           4, 95, tuple(eighths(0, 4, HIHAT, "R")
                        + [n(0, KICK), n(2, KICK), n(2.5, KICK)] + _backbeat())),

    Rhythm("lv13", "Four on Floor", "Kick on every beat under a steady hi-hat.",
           4, 100, tuple(eighths(0, 4, HIHAT, "R") + quarters(0, 4, KICK) + _backbeat())),

    Rhythm("lv14", "Half Time", "Snare only on 3. Everything feels twice as slow.",
           4, 90, tuple(eighths(0, 4, HIHAT, "R") + [n(0, KICK), n(2.5, KICK), n(2, SNARE, "L")])),

    Rhythm("lv15", "Open Hi-Hat", "Lift the left foot on the and of 4 to let the hat ring.",
           4, 95, tuple(eighths(0, 3.5, HIHAT, "R") + [n(3.5, HIHAT, "R"), open_hat(3.4, 0.5)]
                        + [n(0, KICK), n(2, KICK)] + _backbeat())),

    Rhythm("lv16", "Tom Moves", "Walk around the kit: snare, tom 1, tom 2, floor.",
           4, 90, tuple([n(0, SNARE, "R"), n(1, TOM1, "L"), n(2, TOM2, "R"), n(3, FLOOR, "L")])),

    Rhythm("lv17", "Groove & Fill", "One bar of groove, one bar of fill around the toms.",
           8, 95, tuple(_rock() + [n(4, SNARE, "R"), n(4.5, SNARE, "L"),
                                   n(5, TOM1, "R"), n(5.5, TOM1, "L"),
                                   n(6, TOM2, "R"), n(6.5, TOM2, "L"),
                                   n(7, FLOOR, "R"), n(7.5, FLOOR, "L")])),

    Rhythm("lv18", "Shuffle", "Swung eighths - long, short, long, short.",
           4, 90, tuple([n(b, HIHAT, "R") for b in (0, 0.667, 1, 1.667, 2, 2.667, 3, 3.667)]
                        + [n(0, KICK), n(2, KICK)] + _backbeat())),

    Rhythm("lv19", "Crash & Ride", "Open on a crash, then drive the groove on the ride.",
           4, 100, tuple([n(0, CRASH, "R")] + eighths(0.5, 4, RIDE, "R")
                         + [n(0, KICK), n(2.5, KICK)] + _backbeat())),

    Rhythm("lv20", "Full Kit", "Everything you have learned, in two bars.",
           8, 105, tuple([n(0, CRASH, "R")] + eighths(0.5, 4, RIDE, "R")
                         + [n(0, KICK), n(2.5, KICK)] + _backbeat()
                         + eighths(4, 8, HIHAT, "R") + [n(4, KICK), n(6, KICK)]
                         + _backbeat(4) + [n(7.5, FLOOR, "L")])),
]

# --------------------------------------------------------------------------
# Learn Rhythms - standalone grooves to listen to and pick from
# --------------------------------------------------------------------------
GROOVES: list[Rhythm] = [
    Rhythm("gr_rock", "Straight Rock", "The everyday eight-note rock groove.",
           4, 100, tuple(_rock())),

    Rhythm("gr_disco", "Disco", "Four on the floor with an open hat on every and.",
           4, 115, tuple(eighths(0, 4, HIHAT, "R") + quarters(0, 4, KICK) + _backbeat()
                         + [open_hat(1.4, 0.4), open_hat(3.4, 0.4)])),

    Rhythm("gr_halftime", "Half Time", "Wide open and heavy. Snare lands once a bar.",
           4, 85, tuple(eighths(0, 4, HIHAT, "R") + [n(0, KICK), n(2.5, KICK), n(2, SNARE, "L")])),

    Rhythm("gr_shuffle", "Shuffle", "A swung blues feel with a triplet pulse.",
           4, 95, tuple([n(b, HIHAT, "R") for b in (0, 0.667, 1, 1.667, 2, 2.667, 3, 3.667)]
                        + [n(0, KICK), n(2, KICK)] + _backbeat())),

    Rhythm("gr_funk", "Funk", "Syncopated kick with a tight backbeat.",
           4, 100, tuple(eighths(0, 4, HIHAT, "R")
                         + [n(0, KICK), n(0.75, KICK), n(2.5, KICK)] + _backbeat())),

    Rhythm("gr_tom", "Tribal Toms", "Floor tom instead of hi-hat. Big and rolling.",
           4, 90, tuple(eighths(0, 4, FLOOR, "L") + [n(0, KICK), n(2, KICK)]
                        + [n(1, SNARE, "R"), n(3, SNARE, "R")])),

    Rhythm("gr_anthem", "Stadium Anthem", "Two bars: crash-driven groove into a tom fill.",
           8, 100, tuple([n(0, CRASH, "R")] + eighths(0.5, 4, HIHAT, "R")
                         + [n(0, KICK), n(2, KICK)] + _backbeat()
                         + [n(4, SNARE, "R"), n(4.5, TOM1, "L"), n(5, TOM1, "R"),
                            n(5.5, TOM2, "L"), n(6, TOM2, "R"), n(6.5, FLOOR, "L"),
                            n(7, FLOOR, "R"), n(7.5, SNARE, "L"), n(4, KICK), n(6, KICK)])),
]

BY_ID = {r.id: r for r in LEVELS + GROOVES}


def level_number(rhythm: Rhythm):
    for i, lv in enumerate(LEVELS, start=1):
        if lv.id == rhythm.id:
            return i
    return None
