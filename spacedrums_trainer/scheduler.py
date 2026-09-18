"""A 1 ms callback timer.

The 60 fps render loop is too coarse for a click track - a metronome scheduled
on frame boundaries wanders by up to 16 ms, which is audible. This runs the
audio-facing events on their own thread instead.
"""

from __future__ import annotations

import heapq
import itertools
import threading
import time


class Scheduler:
    def __init__(self):
        self._heap: list[tuple[float, int, object]] = []
        self._seq = itertools.count()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def at(self, when: float, callback):
        """Fire `callback` at an absolute time.perf_counter() value."""
        with self._lock:
            heapq.heappush(self._heap, (when, next(self._seq), callback))

    def clear(self):
        with self._lock:
            self._heap.clear()

    def shutdown(self):
        self._stop.set()
        self._thread.join(timeout=0.5)

    def _run(self):
        while not self._stop.is_set():
            now = time.perf_counter()
            fired = []
            with self._lock:
                while self._heap and self._heap[0][0] <= now:
                    fired.append(heapq.heappop(self._heap)[2])
            for callback in fired:
                try:
                    callback()
                except Exception:
                    pass
            time.sleep(0.001)
