"""Sample playback.

Same audio path as the original audio_hub.py: pygame.mixer with a small
buffer, samples read from ./audio next to the repo root. Hits are played from
whichever thread reports them so nothing waits on the render loop.
"""

from __future__ import annotations

import array
import math
import os

import pygame

AUDIO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audio")

SAMPLE_NAMES = ("crash", "snare", "tom1", "tom2", "ride", "floor_tom",
                "hihat_open", "hihat_closed", "kick")

DRUM_SAMPLE = {1: "crash", 2: "snare", 3: "tom1", 4: "tom2", 5: "ride",
               7: "floor_tom", 8: "kick"}
HIHAT_ID = 6

VOLUME_MAP = {1: 0.20, 2: 0.40, 3: 0.60, 4: 0.80, 5: 0.90, 6: 1.00}
HIHAT_CHOKE_MS = 60


def _tone(freq, ms, volume, decay):
    rate = 44100
    frames = int(rate * ms / 1000)
    buf = array.array("h")
    for i in range(frames):
        t = i / rate
        sample = int(32767 * volume * math.exp(-t * decay) * math.sin(2 * math.pi * freq * t))
        buf.append(sample)
        buf.append(sample)
    return pygame.mixer.Sound(buffer=buf.tobytes())


class Kit:
    def __init__(self, volume=0.9):
        pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=256)
        pygame.mixer.init()
        pygame.mixer.set_num_channels(32)

        self.volume = volume
        self.missing: list[str] = []
        self.samples: dict[str, pygame.mixer.Sound] = {}
        for name in SAMPLE_NAMES:
            path = os.path.join(AUDIO_DIR, f"{name}.wav")
            try:
                self.samples[name] = pygame.mixer.Sound(path)
            except (FileNotFoundError, pygame.error):
                self.missing.append(f"{name}.wav")
                self.samples[name] = _tone(180, 60, 0.25, 40)

        self.click_hi = _tone(1600, 26, 0.45, 150)
        self.click_lo = _tone(1050, 22, 0.28, 170)

        self.hat_closed = True
        self._open_hat_channel = None

    # ------------------------------------------------------------------
    def sample_for(self, drum_id):
        if drum_id == HIHAT_ID:
            return "hihat_closed" if self.hat_closed else "hihat_open"
        return DRUM_SAMPLE.get(drum_id)

    def play(self, drum_id, velocity=6, stick_id=None):
        if not pygame.mixer.get_init():
            return
        name = self.sample_for(drum_id)
        sound = self.samples.get(name)
        if sound is None:
            return
        channel = pygame.mixer.find_channel()
        if channel is None:
            return

        gain = VOLUME_MAP.get(velocity, 1.0) * self.volume
        if stick_id == 0:
            channel.set_volume(gain * 0.9, gain * 0.45)
        elif stick_id == 1:
            channel.set_volume(gain * 0.45, gain * 0.9)
        else:
            channel.set_volume(gain, gain)
        channel.play(sound)

        if name == "hihat_open":
            self._open_hat_channel = channel

    def set_hat_closed(self, closed: bool):
        self.hat_closed = closed
        if closed:
            self.choke_hat()

    def choke_hat(self):
        if not pygame.mixer.get_init():
            return
        channel = self._open_hat_channel
        if channel is not None and channel.get_busy():
            channel.fadeout(HIHAT_CHOKE_MS)
        self._open_hat_channel = None

    def click(self, accent=False):
        if not pygame.mixer.get_init():
            return
        channel = pygame.mixer.find_channel()
        if channel is None:
            return
        gain = self.volume * (0.8 if accent else 0.5)
        channel.set_volume(gain, gain)
        channel.play(self.click_hi if accent else self.click_lo)
