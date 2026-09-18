"""Serial link to the ESP32-S3 hub.

Protocol (500000 baud, from README section 10):
    H,<stick_id>,<drum_id>,<velocity>        hit
    B,<stick_id>,<percent>,<millivolts>      battery, every 10 s per stick
    P,<pedal_id>[,<velocity>[,<pressed>]]    pedal

The left pedal is locked to the hi-hat and the right pedal to the kick, so the
game never has to ask which mode the pedals are in.
"""

from __future__ import annotations

import queue
import threading
import time

import serial
from serial.tools import list_ports

KICK_DRUM_ID = 8
HIHAT_PEDAL_DRUM_ID = 9
PEDAL_LEFT, PEDAL_RIGHT = 0, 1

RECONNECT_DELAY = 2.0


def candidate_ports():
    """Likely hub ports, best guess first."""
    ports = []
    for info in list_ports.comports():
        blob = f"{info.device} {info.description} {info.hwid}".lower()
        score = 0
        if "acm" in blob or "cdc" in blob or "usb" in blob:
            score += 2
        if "esp" in blob or "303a" in blob or "xiao" in blob or "seeed" in blob:
            score += 3
        ports.append((score, info.device))
    ports.sort(key=lambda p: -p[0])
    return [device for _, device in ports]


class Hub:
    """Background serial reader. Hits are sounded immediately and queued for scoring."""

    def __init__(self, kit, port=None, baud=500000):
        self.kit = kit
        self.port = port
        self.baud = baud

        self.events: queue.SimpleQueue = queue.SimpleQueue()
        self.battery: dict[int, dict] = {}
        self.connected = False
        self.status = "Looking for hub..."
        self.active_port = None

        self._serial = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------
    def shutdown(self):
        self._stop.set()
        try:
            if self._serial is not None:
                self._serial.close()
        except Exception:
            pass
        self._thread.join(timeout=1.5)

    def feed_hit(self, drum_id, velocity=5, stick_id=None):
        """Inject a hit from the keyboard fallback."""
        self._emit_hit(time.perf_counter(), drum_id, velocity, stick_id)

    def feed_pedal(self, pedal_id, pressed=True, velocity=6):
        self._emit_pedal(time.perf_counter(), pedal_id, velocity, pressed)

    # ------------------------------------------------------------------
    def _emit_hit(self, t, drum_id, velocity, stick_id):
        self.kit.play(drum_id, velocity, stick_id)
        self.events.put(("hit", t, drum_id, velocity, stick_id))

    def _emit_pedal(self, t, pedal_id, velocity, pressed):
        if pedal_id == PEDAL_RIGHT:
            if pressed:
                self._emit_hit(t, KICK_DRUM_ID, velocity, None)
            return
        # Left pedal is the hi-hat: silent, it only decides open vs closed.
        self.kit.set_hat_closed(pressed)
        self.events.put(("pedal", t, HIHAT_PEDAL_DRUM_ID, velocity, pressed))

    # ------------------------------------------------------------------
    def _run(self):
        while not self._stop.is_set():
            if not self._connect():
                time.sleep(RECONNECT_DELAY)
                continue
            try:
                self._read_loop()
            except Exception as exc:
                self.status = f"Hub disconnected: {exc}"
            self.connected = False
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
            time.sleep(1.0)

    def _connect(self):
        for device in ([self.port] if self.port else candidate_ports()):
            if not device:
                continue
            try:
                self._serial = serial.Serial(device, self.baud, timeout=1.0)
            except Exception:
                continue
            self.active_port = device
            self.connected = True
            self.status = f"Hub connected  {device}"
            return True
        self.status = "No hub found - keyboard keys still work"
        return False

    def _read_loop(self):
        ser = self._serial
        while not self._stop.is_set():
            raw = ser.readline()
            if not raw:
                continue  # timeout tick, lets us notice _stop
            t = time.perf_counter()
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            parts = line.split(",")
            try:
                if parts[0] == "H" and len(parts) == 4:
                    self._emit_hit(t, int(parts[2]), int(parts[3]), int(parts[1]))
                elif parts[0] == "P" and len(parts) >= 2:
                    velocity = int(parts[2]) if len(parts) >= 3 else 6
                    pressed = int(parts[3]) == 1 if len(parts) >= 4 else True
                    self._emit_pedal(t, int(parts[1]), velocity, pressed)
                elif parts[0] == "B" and len(parts) == 4:
                    self.battery[int(parts[1])] = {
                        "pct": int(parts[2]), "mv": int(parts[3]), "time": time.time(),
                    }
            except ValueError:
                continue
